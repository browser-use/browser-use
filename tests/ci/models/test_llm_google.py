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


_GEMINI_3_FLASH_MODEL = 'gemini-3-flash-preview'
_GEMINI_THINKING_MODELS = ('gemini-3-pro-preview', _GEMINI_3_FLASH_MODEL, 'gemini-2.5-flash')
_THOUGHT_SUMMARY = 'I should click the button.'
_STRUCTURED_THINKING = 'I should verify the button state.'
_THINKING_SEPARATOR = '\n'
_THINKING_LEVEL = 'low'
_FINAL_TEXT = 'Hello'
_POSITIONAL_MAX_OUTPUT_TOKENS = 4096


def _mock_genai_client(response):
	"""Build a mock genai client returning the supplied response."""
	from unittest.mock import AsyncMock, MagicMock

	mock_client = MagicMock()
	mock_client.aio = MagicMock()
	mock_client.aio.models = AsyncMock()
	mock_client.aio.models.generate_content.return_value = response
	return mock_client, mock_client.aio.models


def _thought_response(final_text: str):
	"""Build a real genai response containing separate thought and answer parts."""
	from google.genai import types

	return types.GenerateContentResponse(
		candidates=[
			types.Candidate(
				content=types.Content(
					role='model',
					parts=[
						types.Part(text=_THOUGHT_SUMMARY, thought=True),
						types.Part(text=final_text),
					],
				),
				finish_reason=types.FinishReason.STOP,
			)
		]
	)


def _agent_mock_llm(agent_output_json: str, provider_thinking: str):
	"""Build an agent LLM response with provider thinking on the envelope."""
	from unittest.mock import AsyncMock

	from browser_use.llm import BaseChatModel
	from browser_use.llm.views import ChatInvokeCompletion

	llm = AsyncMock(spec=BaseChatModel)
	llm.model = 'mock-llm'
	llm._verified_api_keys = True
	llm.provider = 'mock'
	llm.name = 'mock-llm'
	llm.model_name = 'mock-llm'

	async def mock_ainvoke(*args, **kwargs):
		output_format = args[1] if len(args) >= 2 else kwargs.get('output_format')
		assert output_format is not None
		return ChatInvokeCompletion(
			completion=output_format.model_validate_json(agent_output_json),
			thinking=provider_thinking,
			usage=None,
		)

	llm.ainvoke.side_effect = mock_ainvoke
	return llm


class TestGeminiThoughts:
	"""Regression coverage for Gemini thought summaries from issue #5128."""

	def test_constructor_positional_order_is_preserved(self):
		"""New options must not shift the existing positional constructor contract."""
		chat = ChatGoogle('gemini-2.5-flash', 0.5, None, None, -1, None, _POSITIONAL_MAX_OUTPUT_TOKENS)

		assert chat.max_output_tokens == _POSITIONAL_MAX_OUTPUT_TOKENS
		assert chat.include_thoughts is True

	def test_extract_thinking_handles_missing_content(self):
		"""A response candidate without content has no thought summary."""
		from google.genai import types

		response = types.GenerateContentResponse(candidates=[types.Candidate(content=None)])

		assert ChatGoogle(model=_GEMINI_3_FLASH_MODEL, api_key='fake')._extract_thinking(response) is None

	@pytest.mark.asyncio
	@pytest.mark.parametrize('model', _GEMINI_THINKING_MODELS)
	async def test_ainvoke_requests_and_returns_thought_summaries(self, model):
		"""Every thinking model must request and expose thought-summary parts."""
		from unittest.mock import patch

		from browser_use.llm.messages import UserMessage

		mock_client, mock_models = _mock_genai_client(_thought_response(_FINAL_TEXT))
		with patch.object(ChatGoogle, 'get_client', return_value=mock_client):
			result = await ChatGoogle(model=model, api_key='fake').ainvoke([UserMessage(content='Hello')])

		thinking_config = mock_models.generate_content.call_args.kwargs['config']['thinking_config']
		assert thinking_config.get('include_thoughts') is True
		assert result.thinking == _THOUGHT_SUMMARY
		assert result.completion == _FINAL_TEXT

	@pytest.mark.asyncio
	async def test_gemini_3_flash_thinking_level_requests_summaries(self):
		"""Gemini 3 Flash must request summaries when configured with a thinking level."""
		from unittest.mock import patch

		from browser_use.llm.messages import UserMessage

		mock_client, mock_models = _mock_genai_client(_thought_response(_FINAL_TEXT))
		with patch.object(ChatGoogle, 'get_client', return_value=mock_client):
			result = await ChatGoogle(
				model=_GEMINI_3_FLASH_MODEL,
				api_key='fake',
				thinking_level=_THINKING_LEVEL,
			).ainvoke([UserMessage(content='Hello')])

		thinking_config = mock_models.generate_content.call_args.kwargs['config']['thinking_config']
		assert thinking_config.get('include_thoughts') is True
		assert result.thinking == _THOUGHT_SUMMARY

	@pytest.mark.asyncio
	async def test_disabled_thinking_does_not_request_summaries(self):
		"""A zero thinking budget must not request thought summaries."""
		from unittest.mock import patch

		from browser_use.llm.messages import UserMessage

		mock_client, mock_models = _mock_genai_client(_thought_response(_FINAL_TEXT))
		with patch.object(ChatGoogle, 'get_client', return_value=mock_client):
			result = await ChatGoogle(model='gemini-2.5-flash', api_key='fake', thinking_budget=0).ainvoke(
				[UserMessage(content='Hello')]
			)

		thinking_config = mock_models.generate_content.call_args.kwargs['config']['thinking_config']
		assert thinking_config.get('include_thoughts') is not True
		assert result.thinking is None

	@pytest.mark.asyncio
	async def test_structured_output_returns_thought_summaries(self):
		"""Structured JSON output must retain provider thought summaries."""
		from unittest.mock import patch

		from pydantic import BaseModel

		from browser_use.llm.messages import UserMessage

		class Answer(BaseModel):
			answer: str

		mock_client, _ = _mock_genai_client(_thought_response('{"answer": "42"}'))
		with patch.object(ChatGoogle, 'get_client', return_value=mock_client):
			result = await ChatGoogle(model='gemini-2.5-flash', api_key='fake').ainvoke(
				[UserMessage(content='Answer briefly')], output_format=Answer
			)

		assert result.completion.answer == '42'
		assert result.thinking == _THOUGHT_SUMMARY

	@pytest.mark.asyncio
	@pytest.mark.parametrize(
		('agent_kwargs', 'expected_thinking'),
		[
			({}, _THOUGHT_SUMMARY),
			({'use_thinking': False}, None),
			({'flash_mode': True}, None),
		],
	)
	async def test_agent_bridges_provider_thinking_only_when_enabled(self, agent_kwargs, expected_thinking):
		"""Agent history receives provider thinking unless thinking is disabled."""
		from browser_use import Agent
		from browser_use.llm.messages import UserMessage

		if agent_kwargs.get('flash_mode'):
			output_json = '{"memory": "m", "action": [{"done": {"text": "ok", "success": true}}]}'
		else:
			output_json = (
				'{"evaluation_previous_goal": "e", "memory": "m", "next_goal": "n",'
				' "action": [{"done": {"text": "ok", "success": true}}]}'
			)
		agent = Agent(task='Test task', llm=_agent_mock_llm(output_json, _THOUGHT_SUMMARY), **agent_kwargs)

		output = await agent.get_model_output([UserMessage(content='x')])

		assert output.thinking == expected_thinking

	@pytest.mark.asyncio
	async def test_agent_combines_provider_and_structured_thinking(self):
		"""Provider summaries must not replace thinking already present in structured output."""
		from browser_use import Agent
		from browser_use.llm.messages import UserMessage

		output_json = (
			f'{{"thinking": "{_STRUCTURED_THINKING}", "evaluation_previous_goal": "e", "memory": "m", "next_goal": "n",'
			' "action": [{"done": {"text": "ok", "success": true}}]}'
		)
		agent = Agent(task='Test task', llm=_agent_mock_llm(output_json, _THOUGHT_SUMMARY))

		output = await agent.get_model_output([UserMessage(content='x')])

		assert output.thinking == _THINKING_SEPARATOR.join((_THOUGHT_SUMMARY, _STRUCTURED_THINKING))
