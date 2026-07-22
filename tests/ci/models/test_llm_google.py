"""Test Google model button click."""

import pytest

from browser_use.llm.google.chat import ChatGoogle
from tests.ci.models.model_test_helper import run_model_button_click_test


async def test_google_gemini_3_flash_preview(httpserver):
	"""Test Google gemini-3-flash-preview can click a button."""
	await run_model_button_click_test(
		model_class=ChatGoogle,
		model_name='gemini-3-flash-preview',
		api_key_env='GOOGLE_API_KEY',
		extra_kwargs={},
		httpserver=httpserver,
	)


def test_x_goog_api_client_header_is_set():
	"""Test that the x-goog-api-client header is correctly set in the HTTP options."""
	chat = ChatGoogle(model='gemini-flash-latest', api_key='fake')

	# Generate the params used for genai.Client
	params = chat._get_client_params()

	# Extract the header
	http_options = params.get('http_options', {})
	headers = http_options.get('headers', {})

	assert 'x-goog-api-client' in headers, 'x-goog-api-client header missing'
	assert 'browser-use/' in headers['x-goog-api-client'], 'browser-use not found in x-goog-api-client header'


def test_x_goog_api_client_header_with_none_http_options():
	"""Test setting header when http_options is None."""
	chat = ChatGoogle(model='gemini-flash-latest', api_key='fake', http_options=None)
	params = chat._get_client_params()
	http_opts = params.get('http_options', {})
	assert http_opts.get('headers', {}).get('x-goog-api-client', '').startswith('browser-use/')


def test_x_goog_api_client_header_with_pydantic_http_options():
	"""Test setting header when http_options is a types.HttpOptions Pydantic model."""
	from google.genai import types

	pydantic_opts = types.HttpOptions(timeout=30, headers={'custom-header': 'value'})
	chat = ChatGoogle(model='gemini-flash-latest', api_key='fake', http_options=pydantic_opts)
	params = chat._get_client_params()
	http_opts = params.get('http_options', {})

	# Verify it extracts and preserves timeout and custom-header
	assert http_opts.get('timeout') == 30
	assert http_opts.get('headers', {}).get('custom-header') == 'value'
	assert http_opts.get('headers', {}).get('x-goog-api-client', '').startswith('browser-use/')


def test_x_goog_api_client_header_with_dict_http_options():
	"""Test setting header when http_options is a dictionary (types.HttpOptionsDict)."""
	from google.genai import types

	dict_opts: types.HttpOptionsDict = {
		'timeout': 45,
		'headers': {'another-header': 'another-value'},
	}
	chat = ChatGoogle(model='gemini-flash-latest', api_key='fake', http_options=dict_opts)
	params = chat._get_client_params()
	http_opts = params.get('http_options', {})

	# Verify it preserves dictionary values and appends the tracking header
	assert http_opts.get('timeout') == 45
	assert http_opts.get('headers', {}).get('another-header') == 'another-value'
	assert http_opts.get('headers', {}).get('x-goog-api-client', '').startswith('browser-use/')


@pytest.mark.asyncio
async def test_chat_google_temperature_fallback():
	"""Test that ChatGoogle sets temperature config conditionally based on model."""
	from unittest.mock import AsyncMock, MagicMock, patch

	from browser_use.llm.messages import UserMessage

	# Mock get_client to return a mock client with a mock generate_content method
	mock_client = MagicMock()
	mock_aio = MagicMock()
	mock_models = AsyncMock()
	mock_client.aio = mock_aio
	mock_aio.models = mock_models

	# Create mock response
	mock_response = MagicMock()
	mock_response.text = 'Mocked Response'
	mock_response.usage = None
	mock_response.candidates = []
	mock_models.generate_content.return_value = mock_response

	# 1. Non-Gemini 3 model (e.g. gemini-2.5-flash) with no temperature gets 0.5
	with patch.object(ChatGoogle, 'get_client', return_value=mock_client):
		chat = ChatGoogle(model='gemini-2.5-flash', api_key='fake')
		await chat.ainvoke([UserMessage(content='Hello')])

		# Verify generate_content was called with config containing temperature=0.5
		mock_models.generate_content.assert_called_once()
		args, kwargs = mock_models.generate_content.call_args
		assert kwargs['config']['temperature'] == 0.5

	mock_models.generate_content.reset_mock()

	# 2. Gemini 3 model (e.g. gemini-3-flash-preview) with no temperature leaves it unset
	with patch.object(ChatGoogle, 'get_client', return_value=mock_client):
		chat = ChatGoogle(model='gemini-3-flash-preview', api_key='fake')
		await chat.ainvoke([UserMessage(content='Hello')])

		# Verify generate_content was called with config omitting temperature
		mock_models.generate_content.assert_called_once()
		args, kwargs = mock_models.generate_content.call_args
		assert 'temperature' not in kwargs['config']

	mock_models.generate_content.reset_mock()

	# 3. Model with explicitly set temperature preserves it
	with patch.object(ChatGoogle, 'get_client', return_value=mock_client):
		chat = ChatGoogle(model='gemini-3-flash-preview', api_key='fake', temperature=1.0)
		await chat.ainvoke([UserMessage(content='Hello')])

		# Verify generate_content was called with config containing temperature=1.0
		mock_models.generate_content.assert_called_once()
		args, kwargs = mock_models.generate_content.call_args
		assert kwargs['config']['temperature'] == 1.0


@pytest.mark.asyncio
async def test_chat_google_preserves_thought_signature_turn_history_per_session():
	"""Exact user/assistant turns are preserved only within their agent session."""
	from unittest.mock import AsyncMock, MagicMock, patch

	from google.genai import types

	from browser_use.llm.messages import UserMessage

	def signed_response(text: str, signature: bytes) -> types.GenerateContentResponse:
		return types.GenerateContentResponse(
			candidates=[
				types.Candidate(
					content=types.Content(
						role='model',
						parts=[types.Part(text=text, thought_signature=signature)],
					)
				)
			]
		)

	mock_client = MagicMock()
	mock_client.aio.models.generate_content = AsyncMock(
		side_effect=[
			signed_response('first', b'first-signature'),
			signed_response('second', b'second-signature'),
			signed_response('other', b'other-signature'),
		]
	)

	with patch.object(ChatGoogle, 'get_client', return_value=mock_client):
		chat = ChatGoogle(
			model='gemini-3.5-flash-lite',
			api_key='fake',
			thinking_level='high',
			preserve_thought_signatures=True,
		)
		await chat.ainvoke([UserMessage(content='step one')], session_id='agent-a')
		await chat.ainvoke([UserMessage(content='step two')], session_id='agent-a')
		await chat.ainvoke([UserMessage(content='other agent')], session_id='agent-b')

	calls = mock_client.aio.models.generate_content.call_args_list
	assert len(calls[0].kwargs['contents']) == 1
	assert calls[0].kwargs['config']['thinking_config']['thinking_level'] == types.ThinkingLevel.HIGH

	second_contents = calls[1].kwargs['contents']
	assert [content.role for content in second_contents] == ['user', 'model', 'user']
	assert second_contents[0].parts[0].text == 'step one'
	assert second_contents[1].parts[0].text == 'first'
	assert second_contents[1].parts[0].thought_signature == b'first-signature'
	assert second_contents[2].parts[0].text == 'step two'

	# A shared ChatGoogle instance must not leak another agent's history.
	assert len(calls[2].kwargs['contents']) == 1
	assert calls[2].kwargs['contents'][0].parts[0].text == 'other agent'

	assert [content.role for content in chat._thought_signature_histories['agent-a']] == [
		'user',
		'model',
		'user',
		'model',
	]
	agent_a_last_parts = chat._thought_signature_histories['agent-a'][3].parts
	agent_b_last_parts = chat._thought_signature_histories['agent-b'][1].parts
	assert agent_a_last_parts is not None
	assert agent_b_last_parts is not None
	assert agent_a_last_parts[0].text == 'second'
	assert agent_b_last_parts[0].text == 'other'


def test_chat_google_does_not_store_thought_signatures_when_disabled():
	"""The existing stateless behavior remains the default."""
	from google.genai import types

	chat = ChatGoogle(model='gemini-3-flash-preview', api_key='fake')
	response = types.GenerateContentResponse(
		candidates=[
			types.Candidate(
				content=types.Content(
					role='model',
					parts=[types.Part(text='answer', thought_signature=b'opaque')],
				)
			)
		]
	)

	user_contents = [types.Content(role='user', parts=[types.Part.from_text(text='question')])]
	chat._commit_thought_signature_turn(response, user_contents, 'agent-a')

	assert chat._thought_signature_histories == {}
