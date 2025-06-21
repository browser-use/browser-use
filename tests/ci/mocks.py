"""Mock utilities for testing browser-use."""

from unittest.mock import AsyncMock

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage


def create_mock_llm(actions=None):
	"""Create a mock LLM that returns specified actions or a default done action.

	Args:
		actions: Optional list of JSON strings representing actions to return in sequence.
			If not provided, returns a single done action.
			After all actions are exhausted, returns a done action.

	Returns:
		Mock LLM that will return the actions in order, or just a done action if no actions provided.
	"""
	mock = AsyncMock(spec=BaseChatModel)
	mock._verified_api_keys = True
	mock._verified_tool_calling_method = 'raw'
	mock.model_name = 'mock-llm'

	# Default done action
	default_done_action = """
	{
		"thinking": "null",
		"evaluation_previous_goal": "Successfully completed the task",
		"memory": "Task completed",
		"next_goal": "Task completed",
		"action": [
			{
				"done": {
					"text": "Task completed successfully",
					"success": true
				}
			}
		]
	}
	"""

	if actions is None:
		# No actions provided, just return done action
		mock.invoke.return_value = AIMessage(content=default_done_action)

		async def async_invoke(*args, **kwargs):
			return AIMessage(content=default_done_action)

		mock.ainvoke.side_effect = async_invoke
	else:
		# Actions provided, return them in sequence
		action_index = 0

		def get_next_action():
			nonlocal action_index
			if action_index < len(actions):
				action = actions[action_index]
				action_index += 1
				return action
			else:
				return default_done_action

		# Mock the invoke method
		def mock_invoke(*args, **kwargs):
			return AIMessage(content=get_next_action())

		mock.invoke.side_effect = mock_invoke

		# Create an async version
		async def mock_ainvoke(*args, **kwargs):
			return AIMessage(content=get_next_action())

		mock.ainvoke.side_effect = mock_ainvoke

	return mock
