"""Regression test: Gemini sometimes returns a list field of the structured output (the AgentOutput
`action` list, typically) JSON-encoded as a string. ChatGoogle must decode it instead of failing
validation with 'Input should be a valid list' and retrying the step."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import types
from pydantic import BaseModel

from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.messages import UserMessage


class StepOutput(BaseModel):
	thinking: str
	action: list[dict]


ACTIONS = [{'done': {'text': '## Status\nShipment delivered.', 'success': True}}]


def _response(payload: dict[str, Any], parsed: bool) -> types.GenerateContentResponse:
	response = types.GenerateContentResponse(
		candidates=[
			types.Candidate(
				content=types.Content(role='model', parts=[types.Part(text=json.dumps(payload))]),
				finish_reason=types.FinishReason.STOP,
			)
		]
	)
	if parsed:
		response.parsed = payload
	return response


async def _invoke(response: types.GenerateContentResponse, **chat_kwargs: Any) -> StepOutput:
	client = MagicMock()
	client.aio.models.generate_content = AsyncMock(return_value=response)
	chat = ChatGoogle(model='gemini-3-flash-preview', api_key='test', max_retries=1, **chat_kwargs)
	with patch.object(ChatGoogle, 'get_client', return_value=client):
		result = await chat.ainvoke([UserMessage(content='continue')], output_format=StepOutput)
	assert client.aio.models.generate_content.await_count == 1
	return result.completion


@pytest.mark.parametrize(
	'serialized_action',
	[
		json.dumps(ACTIONS),
		# a raw newline inside the JSON string value, which json.loads rejects as a control character
		'[{"done": {"text": "## Status\nShipment delivered.", "success": true}}]',
	],
	ids=['escaped', 'raw newline'],
)
async def test_stringified_action_in_parsed_response_is_decoded(serialized_action: str):
	payload = {'thinking': 'done', 'action': serialized_action}

	completion = await _invoke(_response(payload, parsed=True))

	assert completion.action == ACTIONS


async def test_stringified_action_in_text_response_is_decoded():
	payload = {'thinking': 'done', 'action': json.dumps(ACTIONS)}

	completion = await _invoke(_response(payload, parsed=False))

	assert completion.action == ACTIONS


async def test_stringified_action_in_fallback_json_mode_is_decoded():
	payload = {'thinking': 'done', 'action': json.dumps(ACTIONS)}

	completion = await _invoke(_response(payload, parsed=False), supports_structured_output=False)

	assert completion.action == ACTIONS


async def test_undecodable_action_string_still_fails_validation():
	payload = {'thinking': 'done', 'action': '[not json'}

	with pytest.raises(ModelProviderError):
		await _invoke(_response(payload, parsed=True))
