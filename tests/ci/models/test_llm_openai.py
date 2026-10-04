"""Test OpenAI model button click."""

from types import SimpleNamespace

import pytest

from browser_use.llm.base import is_reasoning_model
from browser_use.llm.messages import UserMessage
from browser_use.llm.openai.chat import ChatOpenAI
from tests.ci.models.model_test_helper import run_model_button_click_test


@pytest.mark.parametrize(
	('model', 'reasoning_models', 'expected'),
	[
		('gpt-4.1', [''], False),
		('gpt-4.1', [' ', ''], False),
		('o3-mini', ['', 'o3'], True),
		('o3-mini', [' o3'], False),
		('gpt-4.1', None, False),
	],
)
def test_reasoning_model_matching_ignores_empty_patterns(model, reasoning_models, expected):
	"""Empty patterns must not match every model name."""
	assert is_reasoning_model(model, reasoning_models) is expected


async def test_openai_gpt_4_1_mini(httpserver):
	"""Test OpenAI gpt-4.1-mini can click a button."""
	await run_model_button_click_test(
		model_class=ChatOpenAI,
		model_name='gpt-4.1-mini',
		api_key_env='OPENAI_API_KEY',
		extra_kwargs={},
		httpserver=httpserver,
	)


@pytest.mark.parametrize('reasoning_models', [[], [''], [' ', '', '']])
async def test_openai_empty_reasoning_model_patterns_preserve_sampling_parameters(monkeypatch, reasoning_models):
	"""Empty reasoning patterns must not classify a regular model as reasoning."""
	captured: dict[str, object] = {}

	class FakeCompletions:
		async def create(self, **kwargs):
			captured.update(kwargs)
			return SimpleNamespace(
				choices=[SimpleNamespace(message=SimpleNamespace(content='ok'), finish_reason='stop')],
				usage=None,
			)

	fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
	llm = ChatOpenAI(
		model='gpt-4.1',
		api_key='test-key',
		temperature=0.7,
		frequency_penalty=0.4,
		reasoning_models=reasoning_models,
	)
	monkeypatch.setattr(llm, 'get_client', lambda: fake_client)

	await llm.ainvoke([UserMessage(content='hello')])

	assert captured['temperature'] == 0.7
	assert captured['frequency_penalty'] == 0.4
	assert 'reasoning_effort' not in captured
	assert 'extra_headers' not in captured


async def test_openai_ainvoke_forwards_session_id_header(monkeypatch):
	"""session_id passed via ainvoke kwargs must be forwarded as x-episod-session in extra_headers."""
	captured: dict[str, object] = {}

	class FakeCompletions:
		async def create(self, **kwargs):
			captured.update(kwargs)
			return SimpleNamespace(
				choices=[SimpleNamespace(message=SimpleNamespace(content='ok'), finish_reason='stop')],
				usage=None,
			)

	fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
	llm = ChatOpenAI(model='gpt-4.1', api_key='test-key')
	monkeypatch.setattr(llm, 'get_client', lambda: fake_client)

	await llm.ainvoke([UserMessage(content='step 1')], session_id='agent-session-42')

	assert captured['extra_headers'] == {'x-episod-session': 'agent-session-42'}


async def test_openai_ainvoke_preserves_caller_extra_headers(monkeypatch):
	"""Explicit extra_headers in kwargs must take precedence over session_id."""
	captured: dict[str, object] = {}

	class FakeCompletions:
		async def create(self, **kwargs):
			captured.update(kwargs)
			return SimpleNamespace(
				choices=[SimpleNamespace(message=SimpleNamespace(content='ok'), finish_reason='stop')],
				usage=None,
			)

	fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
	llm = ChatOpenAI(model='gpt-4.1', api_key='test-key')
	monkeypatch.setattr(llm, 'get_client', lambda: fake_client)

	await llm.ainvoke(
		[UserMessage(content='step 1')],
		session_id='agent-session-42',
		extra_headers={'x-episod-session': 'custom-pin', 'x-trace': '1'},
	)

	assert captured['extra_headers'] == {'x-episod-session': 'custom-pin', 'x-trace': '1'}
