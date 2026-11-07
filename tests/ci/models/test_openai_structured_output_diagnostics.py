"""Exercise structured-output diagnostics through the OpenAI client transport."""

import json

import httpx
import pytest
from pydantic import BaseModel

from browser_use.llm.exceptions import ModelOutputTruncatedError, ModelProviderError
from browser_use.llm.messages import SystemMessage, UserMessage
from browser_use.llm.openai.chat import ChatOpenAI


class Headline(BaseModel):
	"""A minimal structured response for the provider tests."""

	headline: str


async def _invoke(
	content: str,
	*,
	base_url: str | None = 'https://example.com/v1',
	finish_reason: str = 'stop',
	dont_force: bool = False,
):
	"""Send a real OpenAI client request to a local HTTP transport without provider credentials."""

	def respond(request: httpx.Request) -> httpx.Response:
		"""Return the supplied completion after verifying the request includes a JSON schema."""
		request_body = json.loads(request.content)
		if dont_force:
			assert 'response_format' not in request_body
		else:
			assert request_body['response_format']['type'] == 'json_schema'
		return httpx.Response(
			200,
			json={
				'id': 'response',
				'object': 'chat.completion',
				'created': 1,
				'model': 'test-model',
				'choices': [{'index': 0, 'finish_reason': finish_reason, 'message': {'role': 'assistant', 'content': content}}],
			},
		)

	async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
		model = ChatOpenAI(
			model='test-model', api_key='test', base_url=base_url, http_client=client, dont_force_structured_output=dont_force
		)
		return await model.ainvoke(
			[SystemMessage(content='Return a headline.'), UserMessage(content='Hello')], output_format=Headline
		)


async def test_custom_endpoint_non_json_response_includes_structured_output_hint():
	"""A non-JSON reply from a custom endpoint explains the possible compatibility issue."""
	with pytest.raises(ModelProviderError) as exc:
		await _invoke('A headline in plain text')
	assert 'response_format' in str(exc.value)
	assert 'add_schema_to_system_prompt' in str(exc.value)


@pytest.mark.parametrize('content', ['{"other": "valid"}', '[]', '123', '"text"', 'true', 'null'])
async def test_valid_json_keeps_validation_error(content):
	"""Valid JSON with the wrong shape retains its original validation error."""
	with pytest.raises(ModelProviderError) as exc:
		await _invoke(content)
	assert 'add_schema_to_system_prompt' not in str(exc.value)


@pytest.mark.parametrize('content', ['{"headline": "unfinished', '{not json', '[not json', 'tru'])
async def test_invalid_json_includes_structured_output_hint(content):
	"""Malformed objects, arrays and scalar prefixes receive an accurate invalid-JSON diagnostic."""
	with pytest.raises(ModelProviderError) as exc:
		await _invoke(content)
	assert 'invalid JSON' in str(exc.value)
	assert 'add_schema_to_system_prompt' in str(exc.value)


async def test_first_party_non_json_response_keeps_validation_error():
	"""The compatibility hint is limited to explicitly configured endpoints."""
	with pytest.raises(ModelProviderError) as exc:
		await _invoke('A headline in plain text', base_url=None)
	assert 'add_schema_to_system_prompt' not in str(exc.value)


async def test_unforced_request_does_not_claim_json_schema_was_sent():
	"""Requests configured without a schema retain the original validation error."""
	with pytest.raises(ModelProviderError) as exc:
		await _invoke('A headline in plain text', dont_force=True)
	assert 'response_format=json_schema' not in str(exc.value)


async def test_valid_structured_response_is_unchanged():
	"""A valid structured reply continues to return the parsed model."""
	result = await _invoke('{"headline": "A headline"}')
	assert result.completion.headline == 'A headline'


async def test_truncated_response_keeps_truncation_error():
	"""The existing actionable truncation diagnostic takes precedence over the hint."""
	with pytest.raises(ModelOutputTruncatedError):
		await _invoke('A headline in plain text', finish_reason='length')
