import json

import pytest
from pydantic import BaseModel

from browser_use import ChatAtlasCloud as TopLevelChatAtlasCloud
from browser_use.llm import ChatAtlasCloud
from browser_use.llm.messages import SystemMessage, UserMessage


class AtlasResponse(BaseModel):
	status: str


def test_atlascloud_defaults(monkeypatch):
	monkeypatch.setenv('ATLASCLOUD_API_KEY', 'test-key')

	llm = ChatAtlasCloud()

	assert TopLevelChatAtlasCloud is ChatAtlasCloud
	assert llm.provider == 'atlascloud'
	assert llm.model == 'deepseek-ai/deepseek-v4-pro'
	assert str(llm.base_url) == 'https://api.atlascloud.ai/v1'
	assert llm.api_key == 'test-key'
	assert llm.add_schema_to_system_prompt is True
	assert llm.dont_force_structured_output is True


def test_atlascloud_explicit_api_key_takes_precedence(monkeypatch):
	monkeypatch.setenv('ATLASCLOUD_API_KEY', 'environment-key')

	llm = ChatAtlasCloud(api_key='explicit-key')

	assert llm.api_key == 'explicit-key'


@pytest.mark.asyncio
async def test_atlascloud_uses_openai_compatible_chat_completions(httpserver):
	httpserver.expect_oneshot_request(
		'/v1/chat/completions',
		method='POST',
		headers={'Authorization': 'Bearer test-key'},
	).respond_with_json(
		{
			'id': 'chatcmpl-test',
			'object': 'chat.completion',
			'created': 1,
			'model': 'deepseek-ai/deepseek-v4-pro',
			'choices': [
				{
					'index': 0,
					'message': {'role': 'assistant', 'content': '{"status":"ATLAS_OK"}'},
					'finish_reason': 'stop',
				}
			],
			'usage': {'prompt_tokens': 2, 'completion_tokens': 2, 'total_tokens': 4},
		}
	)
	llm = ChatAtlasCloud(
		api_key='test-key',
		base_url=httpserver.url_for('/v1'),
		max_completion_tokens=32,
	)

	result = await llm.ainvoke(
		[SystemMessage(content='Return the requested result.'), UserMessage(content='Set status to ATLAS_OK.')],
		output_format=AtlasResponse,
	)

	assert result.completion.status == 'ATLAS_OK'
	request = httpserver.log[0][0]
	payload = json.loads(request.get_data(as_text=True))
	assert payload['model'] == 'deepseek-ai/deepseek-v4-pro'
	assert payload['max_completion_tokens'] == 32
	assert 'response_format' not in payload
	assert '<json_schema>' in payload['messages'][0]['content']
