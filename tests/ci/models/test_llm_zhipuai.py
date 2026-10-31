"""Unit tests for ZhipuAI and Z.ai client setup, serializers, and factory routing."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from browser_use.llm.exceptions import ModelOutputTruncatedError, ModelProviderError
from browser_use.llm.messages import (
	AssistantMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	Function,
	ImageURL,
	SystemMessage,
	ToolCall,
	UserMessage,
)
from browser_use.llm.models import get_llm_by_name
from browser_use.llm.zhipuai.chat import ChatZai, ChatZhipuAI
from browser_use.llm.zhipuai.serializer import ZhipuAIMessageSerializer


class CapitalResponse(BaseModel):
	country: str
	capital: str


def test_zhipuai_provider_properties():
	chat = ChatZhipuAI(model='glm-5.3-flash')
	assert chat.provider == 'zhipuai'
	assert chat.name == 'glm-5.3-flash'
	assert str(chat.base_url) == 'https://open.bigmodel.cn/api/paas/v4/'

	zai = ChatZai(model='glm-5.3-flash')
	assert zai.provider == 'zai'
	assert zai.name == 'glm-5.3-flash'
	assert str(zai.base_url) == 'https://api.z.ai/api/paas/v4/'


def test_zhipuai_api_key_fallbacks(monkeypatch: pytest.MonkeyPatch):
	# Test explicit key
	chat = ChatZhipuAI(model='glm-5.3-flash', api_key='explicit-key')
	assert chat._client().api_key == 'explicit-key'

	# Test explicit key takes precedence over client_params
	chat_with_params = ChatZhipuAI(
		model='glm-5.3-flash',
		api_key='explicit-key',
		client_params={'api_key': 'ignored-key'},
	)
	assert chat_with_params._client().api_key == 'explicit-key'

	# Test ZHIPUAI_API_KEY
	monkeypatch.delenv('ZHIPUAI_API_KEY', raising=False)
	monkeypatch.delenv('BIGMODEL_API_KEY', raising=False)
	monkeypatch.delenv('ZAI_API_KEY', raising=False)

	# Test ZHIPUAI_API_KEY precedence over BIGMODEL_API_KEY and ZAI_API_KEY
	monkeypatch.setenv('ZHIPUAI_API_KEY', 'zhipuai-env-key')
	monkeypatch.setenv('BIGMODEL_API_KEY', 'bigmodel-env-key')
	monkeypatch.setenv('ZAI_API_KEY', 'zai-env-key')
	assert ChatZhipuAI(model='glm-5.3-flash')._client().api_key == 'zhipuai-env-key'

	# Test fallback to BIGMODEL_API_KEY over ZAI_API_KEY
	monkeypatch.delenv('ZHIPUAI_API_KEY')
	assert ChatZhipuAI(model='glm-5.3-flash')._client().api_key == 'bigmodel-env-key'

	# Test fallback to ZAI_API_KEY
	monkeypatch.delenv('BIGMODEL_API_KEY')
	assert ChatZhipuAI(model='glm-5.3-flash')._client().api_key == 'zai-env-key'

	# Test missing key raises 401 error
	monkeypatch.delenv('ZAI_API_KEY')
	with pytest.raises(ModelProviderError, match='Missing ZhipuAI API key') as exc_info:
		ChatZhipuAI(model='glm-5.3-flash')._client()
	assert exc_info.value.status_code == 401


def test_zai_api_key_fallbacks(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.delenv('ZHIPUAI_API_KEY', raising=False)
	monkeypatch.delenv('BIGMODEL_API_KEY', raising=False)
	monkeypatch.delenv('ZAI_API_KEY', raising=False)

	# Test ZAI_API_KEY precedence
	monkeypatch.setenv('ZAI_API_KEY', 'zai-key')
	monkeypatch.setenv('BIGMODEL_API_KEY', 'bigmodel-key')
	assert ChatZai(model='glm-5.3-flash')._client().api_key == 'zai-key'

	# Test fallback to BIGMODEL_API_KEY
	monkeypatch.delenv('ZAI_API_KEY')
	assert ChatZai(model='glm-5.3-flash')._client().api_key == 'bigmodel-key'

	# Test fallback to ZHIPUAI_API_KEY
	monkeypatch.delenv('BIGMODEL_API_KEY')
	monkeypatch.setenv('ZHIPUAI_API_KEY', 'zhipuai-key')
	assert ChatZai(model='glm-5.3-flash')._client().api_key == 'zhipuai-key'

	# Test missing key raises 401 error
	monkeypatch.delenv('ZHIPUAI_API_KEY')
	with pytest.raises(ModelProviderError, match='Missing Z.ai API key') as exc_info:
		ChatZai(model='glm-5.3-flash')._client()
	assert exc_info.value.status_code == 401


def test_get_llm_by_name_zhipuai(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('ZHIPUAI_API_KEY', 'test-zhipu-key')

	llm_flash = get_llm_by_name('zhipuai_glm_5_3_flash')
	assert isinstance(llm_flash, ChatZhipuAI)
	assert llm_flash.model == 'glm-5.3-flash'
	assert llm_flash.api_key == 'test-zhipu-key'

	llm_base = get_llm_by_name('zhipuai_glm_5_3')
	assert isinstance(llm_base, ChatZhipuAI)
	assert llm_base.model == 'glm-5.3'

	llm_turbo = get_llm_by_name('zhipuai_glm_5v_turbo')
	assert isinstance(llm_turbo, ChatZhipuAI)
	assert llm_turbo.model == 'glm-5v-turbo'


def test_get_llm_by_name_zai(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('ZAI_API_KEY', 'test-zai-key')

	llm_flash = get_llm_by_name('zai_glm_5_3_flash')
	assert isinstance(llm_flash, ChatZai)
	assert llm_flash.model == 'glm-5.3-flash'
	assert llm_flash.api_key == 'test-zai-key'

	llm_base = get_llm_by_name('zai_glm_5_3')
	assert isinstance(llm_base, ChatZai)
	assert llm_base.model == 'glm-5.3'


def test_zhipuai_message_serializer():
	user_msg = UserMessage(
		content=[
			ContentPartTextParam(text='Check this image', type='text'),
			ContentPartImageParam(image_url=ImageURL(url='data:image/png;base64,abc123=='), type='image_url'),
		]
	)
	serialized_user = ZhipuAIMessageSerializer.serialize(user_msg)
	assert serialized_user['role'] == 'user'
	assert isinstance(serialized_user['content'], list)
	assert serialized_user['content'][0] == {'type': 'text', 'text': 'Check this image'}
	assert serialized_user['content'][1] == {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,abc123=='}}

	sys_msg = SystemMessage(content='System prompt')
	serialized_sys = ZhipuAIMessageSerializer.serialize(sys_msg)
	assert serialized_sys == {'role': 'system', 'content': 'System prompt'}

	asst_msg = AssistantMessage(
		content='Calling tool',
		tool_calls=[
			ToolCall(
				id='call_1',
				function=Function(name='click_element', arguments='{"element_id": 42}'),
				type='function',
			)
		],
	)
	serialized_asst = ZhipuAIMessageSerializer.serialize(asst_msg)
	assert serialized_asst['role'] == 'assistant'
	assert serialized_asst['content'] == 'Calling tool'
	assert len(serialized_asst['tool_calls']) == 1
	assert serialized_asst['tool_calls'][0]['id'] == 'call_1'
	assert serialized_asst['tool_calls'][0]['function']['name'] == 'click_element'


def test_zhipuai_request_kwargs_thinking():
	chat_no_think = ChatZhipuAI(model='glm-5.3-flash', thinking=False)
	assert 'extra_body' not in chat_no_think._request_kwargs()

	chat_think = ChatZhipuAI(model='glm-5.3-flash', thinking=True)
	kwargs = chat_think._request_kwargs()
	assert kwargs.get('extra_body') == {'thinking': {'type': 'enabled'}}


@pytest.mark.asyncio
async def test_zhipuai_ainvoke_text():
	chat = ChatZhipuAI(model='glm-5.3-flash', api_key='test-key')

	# Mock completion response
	mock_choice = MagicMock()
	mock_choice.message.content = 'Beijing is the capital of China.'
	mock_choice.finish_reason = 'stop'

	mock_response = MagicMock()
	mock_response.choices = [mock_choice]
	mock_response.usage.prompt_tokens = 15
	mock_response.usage.completion_tokens = 7
	mock_response.usage.total_tokens = 22

	mock_client = MagicMock()
	mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
	chat._client = MagicMock(return_value=mock_client)

	res = await chat.ainvoke([UserMessage(content='Capital of China?')])
	assert res.completion == 'Beijing is the capital of China.'
	assert res.stop_reason == 'stop'
	assert res.usage is not None
	assert res.usage.prompt_tokens == 15
	assert res.usage.completion_tokens == 7
	assert res.usage.total_tokens == 22


@pytest.mark.asyncio
async def test_zhipuai_ainvoke_structured_output():
	chat = ChatZhipuAI(model='glm-5.3-flash', api_key='test-key')

	mock_tool_call = MagicMock()
	mock_tool_call.function.arguments = '{"country": "France", "capital": "Paris"}'

	mock_choice = MagicMock()
	mock_choice.message.tool_calls = [mock_tool_call]
	mock_choice.message.content = None
	mock_choice.finish_reason = 'tool_calls'

	mock_response = MagicMock()
	mock_response.choices = [mock_choice]
	mock_response.usage.prompt_tokens = 25
	mock_response.usage.completion_tokens = 10
	mock_response.usage.total_tokens = 35

	mock_client = MagicMock()
	mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
	chat._client = MagicMock(return_value=mock_client)

	res = await chat.ainvoke([UserMessage(content='Capital of France?')], output_format=CapitalResponse)
	assert isinstance(res.completion, CapitalResponse)
	assert res.completion.country == 'France'
	assert res.completion.capital == 'Paris'
	assert mock_client.chat.completions.create.call_args.kwargs['tool_choice'] == 'auto'


@pytest.mark.asyncio
async def test_zhipuai_ainvoke_truncated_error():
	chat = ChatZhipuAI(model='glm-5.3-flash', api_key='test-key', max_tokens=100)

	mock_choice = MagicMock()
	mock_choice.finish_reason = 'length'
	mock_choice.message.content = 'Incomplete text...'

	mock_response = MagicMock()
	mock_response.choices = [mock_choice]
	mock_response.usage = None

	mock_client = MagicMock()
	mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
	chat._client = MagicMock(return_value=mock_client)

	with pytest.raises(ModelOutputTruncatedError, match='Model output was truncated at max_tokens=100'):
		await chat.ainvoke([UserMessage(content='Tell me a story')])


def test_zhipuai_serializer_refusal_and_non_object_args():
	# Test refusal in AssistantMessage
	msg = AssistantMessage(content='Sorry', refusal='I cannot assist with that request.')
	serialized = ZhipuAIMessageSerializer.serialize(msg)
	assert serialized['role'] == 'assistant'
	assert '[Refusal] I cannot assist with that request.' in serialized['content']

	# Test refusal when content is None
	msg_none = AssistantMessage(content=None, refusal='Refused')
	serialized_none = ZhipuAIMessageSerializer.serialize(msg_none)
	assert serialized_none['content'] == '[Refusal] Refused'

	# Test non-object JSON tool arguments
	tool_call = ToolCall(
		id='call_1',
		function=Function(name='test_func', arguments='"hello"'),
	)
	serialized_tools = ZhipuAIMessageSerializer._serialize_tool_calls([tool_call])
	assert serialized_tools[0]['function']['arguments'] == '"hello"'
