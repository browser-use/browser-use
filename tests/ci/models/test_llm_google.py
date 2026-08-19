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
