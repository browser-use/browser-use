"""Test ChatAnthropicBedrock handles an empty response.content list without crashing."""

from unittest.mock import AsyncMock

import pytest
from anthropic.types import Message, Usage

from browser_use.llm.aws.chat_anthropic import ChatAnthropicBedrock
from browser_use.llm.messages import UserMessage


def _empty_content_message() -> Message:
	return Message(
		id='msg_test',
		content=[],
		model='anthropic.claude-3-5-sonnet-20240620-v1:0',
		role='assistant',
		stop_reason='end_turn',
		stop_sequence=None,
		type='message',
		usage=Usage(input_tokens=5, output_tokens=0),
	)


async def test_ainvoke_handles_empty_content_list(monkeypatch: pytest.MonkeyPatch) -> None:
	llm = ChatAnthropicBedrock(aws_region='us-east-1', aws_access_key='x', aws_secret_key='y')

	fake_client = AsyncMock()
	fake_client.messages.create = AsyncMock(return_value=_empty_content_message())
	monkeypatch.setattr(llm, 'get_client', lambda: fake_client)

	result = await llm.ainvoke([UserMessage(content='hi')])

	assert result.completion == ''
