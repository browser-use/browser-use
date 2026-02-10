"""Test OpenAI usage token counting."""

from unittest.mock import MagicMock


def test_get_usage_does_not_double_count_reasoning_tokens():
	from openai.types.chat.chat_completion import ChatCompletion

	from browser_use.llm.openai.chat import ChatOpenAI

	mock_response = MagicMock(spec=ChatCompletion)
	mock_response.usage.prompt_tokens = 100
	mock_response.usage.completion_tokens = 500
	mock_response.usage.total_tokens = 600
	mock_response.usage.completion_tokens_details.reasoning_tokens = 400
	mock_response.usage.prompt_tokens_details = None

	client = ChatOpenAI(model='o4-mini')
	usage = client._get_usage(mock_response)

	assert usage is not None
	assert usage.completion_tokens == 500
	assert usage.prompt_tokens == 100
	assert usage.total_tokens == 600
