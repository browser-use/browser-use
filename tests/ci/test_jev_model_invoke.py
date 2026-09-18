"""Mini executes through native models; BU2 verifies any proposed final answer."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import create_model

from browser_use.agent.jev import JevPolicy
from browser_use.agent.views import AgentOutput, AgentState
from browser_use.llm.browser_use.chat import ChatBrowserUse
from browser_use.llm.messages import UserMessage
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.views import ClickElementActionIndexOnly, DoneAction


def output(actions):
	action_model = create_model(
		'InvokeActions',
		__base__=ActionModel,
		click=(ClickElementActionIndexOnly | None, None),
		done=(DoneAction | None, None),
	)
	output_model = AgentOutput.type_with_custom_actions_flash_mode(action_model)
	return output_model.model_validate({'memory': 'Original observed evidence.', 'action': actions})


def response(actions, usage=True):
	return ChatInvokeCompletion(
		completion=output(actions),
		usage=ChatInvokeUsage(
			prompt_tokens=100,
			completion_tokens=20,
			total_tokens=120,
			prompt_cached_tokens=0,
			prompt_cache_creation_tokens=0,
			prompt_image_tokens=0,
		)
		if usage
		else None,
	)


def setup(monkeypatch, mini_response=None):
	monkeypatch.setenv('TYPESAFE_API_KEY', 'unit-test-no-network')
	policy = cast(Any, JevPolicy('model', None))
	policy.use_mini = True
	mini_response = mini_response or response([{'click': {'index': 7}}])
	policy.mini_llm = SimpleNamespace(ainvoke=AsyncMock(return_value=mini_response))
	parent = ChatBrowserUse(api_key='unit-test-no-network', base_url='https://unit.test.invalid')
	parent_response = response([{'done': {'text': 'Verified by BU2'}}])
	parent.ainvoke = AsyncMock(return_value=parent_response)
	agent = SimpleNamespace(
		llm=parent,
		settings=SimpleNamespace(page_extraction_llm=parent),
		token_cost_service=SimpleNamespace(register_llm=Mock()),
		state=AgentState(n_steps=2),
	)
	messages = [UserMessage(content='Full original state and evidence')]
	kwargs = {'output_format': type(mini_response.completion), 'session_id': 'same-session'}
	return policy, agent, messages, kwargs, parent_response, mini_response


async def test_mini_native_action_preserves_parent_extraction_and_input(monkeypatch):
	policy, agent, messages, kwargs, _, expected = setup(monkeypatch)
	parent = agent.llm
	before = [m.model_dump() for m in messages]
	assert await policy.invoke(agent, messages, kwargs) is expected
	assert [m.model_dump() for m in messages] == before
	assert agent.llm is parent and agent.settings.page_extraction_llm is parent
	parent.ainvoke.assert_not_awaited()
	policy.mini_llm.ainvoke.assert_awaited_once_with(messages, **kwargs)
	assert policy.mini_calls == 1
	assert policy.mini_unknown_cost_calls == 0


@pytest.mark.parametrize(
	'actions', [[{'done': {'text': 'Unverified'}}], [{'click': {'index': 7}}, {'done': {'text': 'Unverified'}}]]
)
async def test_any_mini_done_is_discarded_before_execution_and_rechecked_by_bu2(monkeypatch, actions):
	policy, agent, messages, kwargs, expected, _ = setup(monkeypatch, response(actions))
	assert await policy.invoke(agent, messages, kwargs) is expected
	assert policy.mini_final_verifications == 1
	agent.llm.ainvoke.assert_awaited_once_with(messages, **kwargs)
	assert 'Unverified' not in str(agent.llm.ainvoke.call_args)


@pytest.mark.parametrize('error', [RuntimeError('private provider payload'), TimeoutError()])
async def test_mini_error_uses_bu2_and_keeps_unknown_attempt_cost(monkeypatch, error):
	policy, agent, messages, kwargs, expected, _ = setup(monkeypatch)
	policy.mini_llm.ainvoke.side_effect = error
	assert await policy.invoke(agent, messages, kwargs) is expected
	assert policy.mini_unknown_cost_calls == 1
	assert 'private provider payload' not in str(policy.client.events)
	agent.llm.ainvoke.assert_awaited_once_with(messages, **kwargs)


async def test_missing_usage_is_not_zero_cost(monkeypatch):
	policy, agent, messages, kwargs, _, expected = setup(monkeypatch, response([{'click': {'index': 7}}], usage=False))
	assert await policy.invoke(agent, messages, kwargs) is expected
	assert policy.mini_unknown_cost_calls == 1


async def test_cancelled_mini_does_not_invoke_bu2(monkeypatch):
	policy, agent, messages, kwargs, _, _ = setup(monkeypatch)
	policy.mini_llm.ainvoke.side_effect = asyncio.CancelledError()
	with pytest.raises(asyncio.CancelledError):
		await policy.invoke(agent, messages, kwargs)
	agent.llm.ainvoke.assert_not_awaited()
	assert policy.mini_unknown_cost_calls == 1


async def test_unexpected_mini_output_schema_uses_parent(monkeypatch):
	policy, agent, messages, kwargs, expected, _ = setup(monkeypatch)
	policy.mini_llm.ainvoke.return_value = ChatInvokeCompletion(completion='not an AgentOutput', usage=None)
	assert await policy.invoke(agent, messages, kwargs) is expected
	agent.llm.ainvoke.assert_awaited_once_with(messages, **kwargs)


async def test_full_route_never_invokes_mini(monkeypatch):
	policy, agent, messages, kwargs, expected, _ = setup(monkeypatch)
	policy.use_mini = False
	assert await policy.invoke(agent, messages, kwargs) is expected
	policy.mini_llm.ainvoke.assert_not_awaited()
	assert policy.mini_calls == 0


async def test_mini_client_clones_endpoint_and_registers_usage_once(monkeypatch):
	policy, agent, messages, kwargs, _, expected = setup(monkeypatch)
	policy.mini_llm = None
	mini_invoke = AsyncMock(return_value=expected)
	monkeypatch.setattr(ChatBrowserUse, 'ainvoke', mini_invoke)
	assert await policy.invoke(agent, messages, kwargs) is expected
	mini = cast(ChatBrowserUse, policy.mini_llm)
	assert mini.model == 'bu-2-0-mini-preview'
	assert mini.api_key == agent.llm.api_key
	assert mini.base_url == agent.llm.base_url
	assert mini.timeout == 20 and mini.max_retries == 1
	assert mini.fast == agent.llm.fast
	agent.state.n_steps += 1
	assert await policy.invoke(agent, messages, kwargs) is expected
	assert policy.mini_llm is mini
	agent.token_cost_service.register_llm.assert_called_once_with(mini)


async def test_empty_mini_output_falls_back_and_same_step_never_repeats_mini(monkeypatch):
	policy, agent, messages, kwargs, full, mini = setup(monkeypatch)
	mini.completion.action = []
	assert await policy.invoke(agent, messages, kwargs) is full
	assert await policy.invoke(agent, messages, kwargs) is full
	assert policy.mini_calls == 1
	assert policy.full_calls == 2
	policy.mini_llm.ainvoke.assert_awaited_once()
