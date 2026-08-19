"""Regression tests for #5360: empty-action recovery must insert a valid done action.

After create_action_model() switched to a RootModel union of single-action models,
`self.ActionModel()` is invalid (no all-optional flat shape). The empty-action
safety net must construct a proper `done` action instead of raising ValidationError.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentOutput
from browser_use.llm.base import BaseChatModel
from browser_use.llm.views import ChatInvokeCompletion
from browser_use.tools.service import Tools


def _empty_agent_output(output_format: type[AgentOutput]) -> AgentOutput:
	"""Build an AgentOutput with action=[] that still passes type construction."""
	# model_construct skips validation so we can force empty actions without
	# fighting the dynamic action schema constraints.
	return output_format.model_construct(
		thinking='',
		evaluation_previous_goal='',
		memory='',
		next_goal='',
		action=[],
	)


def _create_empty_action_llm() -> tuple[BaseChatModel, dict[str, int]]:
	"""LLM that always returns an AgentOutput with zero actions.

	Returns (llm, counters) where counters['ainvoke'] tracks LLM calls.
	"""
	tools = Tools()
	ActionModel = tools.registry.create_action_model()
	AgentOutputWithActions = AgentOutput.type_with_custom_actions(ActionModel)

	llm = AsyncMock(spec=BaseChatModel)
	llm.model = 'empty-action-model'
	llm._verified_api_keys = True
	llm.provider = 'test'
	llm.name = 'empty-action-model'
	llm.model_name = 'empty-action-model'

	counters = {'ainvoke': 0}

	async def mock_ainvoke(*args, **kwargs):
		counters['ainvoke'] += 1
		output_format = None
		if len(args) >= 2:
			output_format = args[1]
		elif 'output_format' in kwargs:
			output_format = kwargs['output_format']

		if output_format is None:
			return ChatInvokeCompletion(completion='{"action":[]}', usage=None)

		# Prefer agent-provided format so nested ActionModel types match.
		fmt = output_format if issubclass(output_format, AgentOutput) else AgentOutputWithActions
		return ChatInvokeCompletion(completion=_empty_agent_output(fmt), usage=None)

	llm.ainvoke.side_effect = mock_ainvoke
	return llm, counters


def test_action_model_empty_ctor_raises_validation_error():
	"""Document the regression root cause: bare ActionModel() is invalid."""
	AM = Tools().registry.create_action_model()
	with pytest.raises(ValidationError):
		AM()


def test_done_action_model_constructs_fallback_done():
	"""DoneActionModel validates a fallback done payload."""
	DoneAM = Tools().registry.create_action_model(include_actions=['done'])
	action = DoneAM.model_validate({'done': {'success': False, 'text': 'No next action returned by LLM!'}})
	dumped = action.model_dump(exclude_unset=True)
	assert 'done' in dumped
	assert dumped['done']['success'] is False
	assert dumped['done']['text'] == 'No next action returned by LLM!'


def test_full_action_model_constructs_with_done_kwargs():
	"""Union ActionModel also validates a done action payload."""
	AM = Tools().registry.create_action_model()
	action = AM.model_validate({'done': {'success': False, 'text': 'No next action returned by LLM!'}})
	dumped = action.model_dump(exclude_unset=True)
	assert 'done' in dumped
	assert dumped['done']['success'] is False


async def test_get_model_output_with_retry_inserts_done_without_validation_error():
	"""Empty LLM twice → fallback done action, no ValidationError."""
	llm, counters = _create_empty_action_llm()
	agent = Agent(task='test empty action recovery', llm=llm)

	# Two empty responses: first detection + retry, then fallback insertion.
	result = await agent._get_model_output_with_retry([])

	assert result.action is not None
	assert len(result.action) == 1

	action_dump = result.action[0].model_dump(exclude_unset=True)
	assert 'done' in action_dump
	assert action_dump['done']['success'] is False
	assert action_dump['done']['text'] == 'No next action returned by LLM!'

	# Primary + retry LLM calls (before insert; insert itself is pure)
	assert counters['ainvoke'] == 2


async def test_get_model_output_with_retry_done_action_is_executable():
	"""Fallback done action must be consumable by tools.act / multi_act dump path."""
	llm, _ = _create_empty_action_llm()
	agent = Agent(task='test empty action recovery', llm=llm)
	result = await agent._get_model_output_with_retry([])

	# multi_act iterates model_dump(exclude_unset=True) keys as action names
	action_data = result.action[0].model_dump(exclude_unset=True)
	action_name = next(iter(action_data.keys()))
	assert action_name == 'done'
