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


# A 1x1 PNG, small enough to inline and still be a real decodable image.
_PNG_1PX = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='


def _flatten(contents) -> list:
	"""Flatten serialized Google contents into a single list of parts."""
	return [part for content in contents for part in (content.parts or [])]


def _describe(contents) -> tuple[str, int]:
	"""Summarise serialized Google contents as (all text, number of inline images)."""
	parts = _flatten(contents)
	return ''.join(part.text or '' for part in parts), sum(1 for part in parts if part.inline_data is not None)


def test_include_system_in_user_keeps_list_content_parts():
	"""include_system_in_user must prepend the system text, not replace the user content.

	With vision on, the agent's user message is a list of parts, and every part of it was
	being dropped from the first user message.
	"""
	from browser_use.llm.google.serializer import GoogleMessageSerializer
	from browser_use.llm.messages import (
		ContentPartImageParam,
		ContentPartTextParam,
		ImageURL,
		SystemMessage,
		UserMessage,
	)

	messages = [
		SystemMessage(content='You are a browser agent.'),
		UserMessage(
			content=[
				ContentPartTextParam(text='<browser_state>the page and the task live here</browser_state>'),
				ContentPartImageParam(image_url=ImageURL(url=f'data:image/png;base64,{_PNG_1PX}', media_type='image/png')),
			]
		),
	]

	contents, system_instruction = GoogleMessageSerializer.serialize_messages(messages, include_system_in_user=True)

	assert system_instruction is None, 'system message should have moved into the user turn'
	text, images = _describe(contents)
	assert 'You are a browser agent.' in text
	assert '<browser_state>the page and the task live here</browser_state>' in text, 'user text was dropped'
	assert images == 1, 'screenshot was dropped'


def test_include_system_in_user_string_content_is_merged_into_one_part():
	"""String content keeps the existing behaviour: system text and user text in a single part."""
	from browser_use.llm.google.serializer import GoogleMessageSerializer
	from browser_use.llm.messages import SystemMessage, UserMessage

	messages = [
		SystemMessage(content='You are a browser agent.'),
		UserMessage(content='Buy a red stapler'),
	]

	contents, system_instruction = GoogleMessageSerializer.serialize_messages(messages, include_system_in_user=True)

	assert system_instruction is None
	parts = _flatten(contents)
	assert len(parts) == 1
	assert parts[0].text == 'You are a browser agent.\n\nBuy a red stapler'


def test_multiple_system_messages_are_preserved_when_extracted():
	"""Extracted system instructions retain every message in their original order."""
	from browser_use.llm.google.serializer import GoogleMessageSerializer
	from browser_use.llm.messages import SystemMessage, UserMessage

	messages = [
		SystemMessage(content='Follow the base system rule.'),
		SystemMessage(content='Also follow the additional system rule.'),
		UserMessage(content='Continue the task.'),
	]

	contents, system_instruction = GoogleMessageSerializer.serialize_messages(messages)

	assert system_instruction == ('Follow the base system rule.\n\nAlso follow the additional system rule.')
	text, images = _describe(contents)
	assert text == 'Continue the task.'
	assert images == 0


def test_include_system_in_user_keeps_the_agent_state_message(tmp_path):
	"""End-to-end shape: what the agent actually builds with vision on must survive serialization."""
	from browser_use.agent.prompts import AgentMessagePrompt, SystemPrompt
	from browser_use.agent.views import AgentStepInfo
	from browser_use.browser.views import BrowserStateSummary, PageInfo, TabInfo
	from browser_use.dom.views import SerializedDOMState
	from browser_use.filesystem.file_system import FileSystem
	from browser_use.llm.google.serializer import GoogleMessageSerializer

	browser_state = BrowserStateSummary(
		url='https://example.test/foo',
		title='Test',
		tabs=[TabInfo(target_id='abcd1234', url='https://example.test/foo', title='Test')],
		page_info=PageInfo(
			viewport_width=1280,
			viewport_height=720,
			page_width=1280,
			page_height=1440,
			scroll_x=0,
			scroll_y=0,
			pixels_above=0,
			pixels_below=720,
			pixels_left=0,
			pixels_right=0,
		),
		dom_state=SerializedDOMState(_root=None, selector_map={}),
		is_pdf_viewer=False,
		recent_events=None,
		closed_popup_messages=[],
		screenshot=_PNG_1PX,
	)
	user_message = AgentMessagePrompt(
		browser_state_summary=browser_state,
		file_system=FileSystem(base_dir=str(tmp_path), create_default_files=False),
		agent_history_description='<step>existing history</step>',
		task='Buy a red stapler',
		step_info=AgentStepInfo(step_number=1, max_steps=50),
		screenshots=[_PNG_1PX],
	).get_user_message(use_vision=True)
	assert isinstance(user_message.content, list), 'vision messages are lists of parts'

	messages = [SystemPrompt(max_actions_per_step=5).get_system_message(), user_message]
	contents, _ = GoogleMessageSerializer.serialize_messages(messages, include_system_in_user=True)

	text, images = _describe(contents)
	assert 'Buy a red stapler' in text, 'the task never reached the model'
	assert images == 1, 'the screenshot never reached the model'
