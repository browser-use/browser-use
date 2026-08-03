"""
Tests for Agent's empty-action recovery path.

When the LLM returns no actions, `Agent._get_model_output_with_retry()` retries once and,
if the retry is also empty, substitutes a `done` action so the agent terminates cleanly
instead of raising.

Regression coverage for the case where that fallback was built by instantiating
`self.ActionModel()` with no arguments — which raises `ValidationError`, because
`Registry.create_action_model()` returns a union of single-action models rather than a
flat all-optional model.
"""

import tempfile
from unittest.mock import AsyncMock

from pydantic import BaseModel

from browser_use import Agent
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm import BaseChatModel
from browser_use.llm.views import ChatInvokeCompletion

EMPTY_ACTION_RESPONSE = """
{
	"thinking": "null",
	"evaluation_previous_goal": "Nothing yet",
	"memory": "Nothing yet",
	"next_goal": "Decide what to do",
	"action": []
}
"""

VALID_ACTION_RESPONSE = """
{
	"thinking": "null",
	"evaluation_previous_goal": "Nothing yet",
	"memory": "Nothing yet",
	"next_goal": "Finish",
	"action": [{"done": {"text": "all good", "success": true}}]
}
"""


def create_mock_llm(responses: list[str]) -> BaseChatModel:
	"""Create a mock LLM that returns `responses` in order, repeating the last one when exhausted."""
	llm = AsyncMock(spec=BaseChatModel)
	llm.model = 'mock-llm'
	llm.provider = 'mock'
	llm.name = 'mock-llm'
	llm.model_name = 'mock-llm'
	llm._verified_api_keys = True

	call_index = 0

	async def mock_ainvoke(*args, **kwargs):
		nonlocal call_index
		output_format = kwargs.get('output_format') or (args[1] if len(args) >= 2 else None)
		assert output_format is not None, 'Agent should always request structured output'

		payload = responses[min(call_index, len(responses) - 1)]
		call_index += 1
		return ChatInvokeCompletion(completion=output_format.model_validate_json(payload), usage=None)

	llm.ainvoke = mock_ainvoke
	return llm


async def test_persistently_empty_actions_fall_back_to_done():
	"""Two empty responses in a row should yield a done action, not raise."""
	agent = Agent(task='test task', llm=create_mock_llm([EMPTY_ACTION_RESPONSE]))

	model_output = await agent._get_model_output_with_retry([])

	assert len(model_output.action) == 1
	action_dump = model_output.action[0].model_dump(exclude_unset=True)
	assert next(iter(action_dump)) == 'done', 'fallback action must be a done action'
	assert action_dump['done']['success'] is False
	assert action_dump['done']['text'] == 'No next action returned by LLM!'


async def test_persistently_empty_actions_do_not_raise_with_structured_output():
	"""The recovery path must not raise when done uses StructuredOutputAction, which has no `text`.

	A structured `done` requires `data` typed to the caller's schema, which cannot be synthesised
	without inventing values the agent never observed. So the fallback builds an empty shell: the
	recovery path returns normally instead of raising, and executing the action surfaces an
	ordinary ActionResult error rather than an uncaught exception escaping into step().
	"""

	class Output(BaseModel):
		answer: str

	agent = Agent(
		task='test task',
		llm=create_mock_llm([EMPTY_ACTION_RESPONSE]),
		output_model_schema=Output,
	)

	model_output = await agent._get_model_output_with_retry([])

	assert len(model_output.action) == 1
	action_dump = model_output.action[0].model_dump(exclude_unset=True)
	assert next(iter(action_dump)) == 'done', 'fallback action must be a done action'
	assert action_dump['done']['success'] is False


async def test_fallback_done_action_is_executable():
	"""The fallback must survive execution, not merely construction.

	`Tools.act` re-validates the action against its registered param model, so an action that
	constructs but fails that validation would still break the run.
	"""
	agent = Agent(task='test task', llm=create_mock_llm([EMPTY_ACTION_RESPONSE]))
	model_output = await agent._get_model_output_with_retry([])

	file_system = FileSystem(tempfile.mkdtemp())
	result = await agent.tools.act(
		action=model_output.action[0],
		browser_session=None,  # type: ignore[arg-type] - the done handler does not request a browser session
		file_system=file_system,
	)

	assert result.error is None
	assert result.is_done is True
	assert result.success is False
	assert result.extracted_content == 'No next action returned by LLM!'


async def test_empty_action_recovers_on_retry():
	"""An empty first response followed by a valid one should use the retried action, not the fallback."""
	agent = Agent(task='test task', llm=create_mock_llm([EMPTY_ACTION_RESPONSE, VALID_ACTION_RESPONSE]))

	model_output = await agent._get_model_output_with_retry([])

	assert len(model_output.action) == 1
	action_dump = model_output.action[0].model_dump(exclude_unset=True)
	assert action_dump['done']['text'] == 'all good'
	assert action_dump['done']['success'] is True


async def test_non_empty_action_is_returned_unchanged():
	"""A valid first response should not trigger the retry path at all."""
	agent = Agent(task='test task', llm=create_mock_llm([VALID_ACTION_RESPONSE]))

	model_output = await agent._get_model_output_with_retry([])

	assert len(model_output.action) == 1
	assert model_output.action[0].model_dump(exclude_unset=True)['done']['text'] == 'all good'
