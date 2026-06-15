"""Tests for the ChatBrowserUse cloud client."""

import pytest

from browser_use.llm.browser_use.chat import ChatBrowserUse
from browser_use.llm.messages import UserMessage
from tests.ci.models.model_test_helper import run_model_button_click_test

# A syntactically-valid key so the constructor doesn't bail before we reach the
# code under test. These unit tests never hit the network.
TEST_API_KEY = 'test-key-not-real'


async def test_browseruse_bu_latest(httpserver):
	"""Test Browser Use bu-latest can click a button."""
	await run_model_button_click_test(
		model_class=ChatBrowserUse,
		model_name='bu-latest',
		api_key_env='BROWSER_USE_API_KEY',
		extra_kwargs={},
		httpserver=httpserver,
	)


# --- Model validation -------------------------------------------------------


def test_default_model_is_bu_2_0():
	chat = ChatBrowserUse(api_key=TEST_API_KEY)
	assert chat.model == 'bu-2-0'
	assert chat.provider == 'browser-use'


@pytest.mark.parametrize('alias', ['bu-1-0', 'bu-2-0'])
def test_bu_aliases_are_accepted(alias):
	chat = ChatBrowserUse(model=alias, api_key=TEST_API_KEY)
	assert chat.model == alias
	assert chat.name == alias
	assert chat.provider == 'browser-use'


def test_bu_latest_normalizes_to_bu_2_0():
	chat = ChatBrowserUse(model='bu-latest', api_key=TEST_API_KEY)
	assert chat.model == 'bu-2-0'
	assert chat.name == 'bu-2-0'


@pytest.mark.parametrize(
	'model',
	[
		'anthropic/claude-sonnet-4-6',
		'openai/gpt-5.5',
		'google/gemini-3-pro',
		'browser-use/bu-30b-a3b-preview',
	],
)
def test_provider_prefixed_models_are_accepted(model):
	"""Provider-prefixed ids are accepted and forwarded verbatim (the gateway resolves them)."""
	chat = ChatBrowserUse(model=model, api_key=TEST_API_KEY)
	assert chat.model == model
	assert chat.name == model
	# Always routes through the browser-use gateway, whatever the target model.
	assert chat.provider == 'browser-use'


@pytest.mark.parametrize('model', ['gpt-5', 'claude-sonnet-4-6', 'bu-9-9', 'random-model'])
def test_bare_model_ids_are_rejected(model):
	"""Bare ids (no bu-* alias, no provider/ prefix) are rejected."""
	with pytest.raises(ValueError, match='Invalid model'):
		ChatBrowserUse(model=model, api_key=TEST_API_KEY)


async def test_provider_prefixed_model_forwarded_in_payload(httpserver):
	"""The provider-prefixed id must be sent verbatim in the request body."""
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_json({'completion': 'hello from gateway'})

	chat = ChatBrowserUse(
		model='anthropic/claude-sonnet-4-6',
		api_key=TEST_API_KEY,
		base_url=httpserver.url_for('/').rstrip('/'),
	)
	result = await chat.ainvoke([UserMessage(content='hi')])

	assert result.completion == 'hello from gateway'

	# Check the posted body.
	request, _ = httpserver.log[-1]
	body = request.get_json()
	assert body['model'] == 'anthropic/claude-sonnet-4-6'
	assert body['request_type'] == 'browser_agent'


# --- Agent screenshot auto-config -------------------------------------------


# Both the classic and beta agents auto-config the Claude screenshot size, so both
# must strip the provider prefix for gateway ids.
@pytest.mark.parametrize('agent_path', ['classic', 'beta'])
@pytest.mark.parametrize(
	'model,expected_size',
	[
		# Claude Sonnet via the gateway keeps the auto-config; the prefix must not break detection.
		('anthropic/claude-sonnet-4-6', (1400, 850)),
		# Non-Claude models keep the default.
		('bu-2-0', None),
		('openai/gpt-5.5', None),
	],
)
def test_claude_sonnet_screenshot_autoconfig_through_gateway(agent_path, model, expected_size):
	if agent_path == 'classic':
		from browser_use.agent.service import Agent
	else:
		from browser_use.beta import Agent

	llm = ChatBrowserUse(model=model, api_key=TEST_API_KEY)
	agent = Agent(task='test', llm=llm)
	assert agent.browser_session is not None
	assert agent.browser_session.llm_screenshot_size == expected_size
