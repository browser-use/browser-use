"""The error a user gets when an endpoint ignores response_format."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import UserMessage
from browser_use.llm.openai.chat import ChatOpenAI

HINT = 'may not support response_format=json_schema'


class Headline(BaseModel):
	headline: str


def _response(content: str):
	return SimpleNamespace(
		choices=[
			SimpleNamespace(
				message=SimpleNamespace(content=content, refusal=None),
				finish_reason='stop',
			)
		],
		usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15, prompt_tokens_details=None),
	)


async def _invoke(content: str, **kwargs):
	llm = ChatOpenAI(model='gpt-4o', api_key='x', **kwargs)
	client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=_response(content)))))
	with patch.object(type(llm), 'get_client', return_value=client):
		return await llm.ainvoke([UserMessage(content='hi')], output_format=Headline)


async def test_prose_from_a_custom_endpoint_names_the_endpoint():
	with pytest.raises(ModelProviderError) as exc:
		await _invoke('**Cats: The Enigma**', base_url='http://localhost:9/v1')

	assert HINT in str(exc.value)
	assert 'http://localhost:9/v1' in str(exc.value)
	assert 'add_schema_to_system_prompt' in str(exc.value)


@pytest.mark.parametrize(
	'content',
	['{"headline": "Cats are', '{"title": "Cats"}', '[]', '123', '"not an object"', 'true', 'null'],
	ids=['truncated', 'wrong-shape', 'wrong-type', 'int', 'string', 'bool', 'null'],
)
async def test_broken_json_keeps_the_original_error(content):
	"""The endpoint produced JSON that does not match the schema.

	Includes bare scalars, which are valid JSON and so are the model's problem
	rather than evidence that the endpoint dropped the schema.
	"""
	with pytest.raises(ModelProviderError) as exc:
		await _invoke(content, base_url='http://localhost:9/v1')

	assert HINT not in str(exc.value)


async def test_prose_from_a_first_party_endpoint_keeps_the_original_error():
	"""Without a base_url there is no custom endpoint to blame."""
	with pytest.raises(ModelProviderError) as exc:
		await _invoke('**Cats: The Enigma**')

	assert HINT not in str(exc.value)
