"""Test OpenAI model button click."""

from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

from browser_use.llm.base import is_reasoning_model
from browser_use.llm.messages import UserMessage
from browser_use.llm.openai.chat import ChatOpenAI
from tests.ci.models.model_test_helper import run_model_button_click_test


@pytest.mark.parametrize('model', ['gpt-6-astra', 'gpt-5.6-luna'])
@pytest.mark.parametrize('structured', [False, True])
async def test_current_openai_models_send_compatible_requests(model, structured):
	"""Exercise SDK serialization for plain and schema-constrained responses."""

	class Answer(BaseModel):
		answer: str

	requests = []

	def respond(request):
		import json

		requests.append(json.loads(request.content))
		return httpx.Response(
			200,
			json={
				'id': 'chatcmpl-test',
				'object': 'chat.completion',
				'created': 0,
				'model': model,
				'choices': [
					{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{"answer":"ok"}'}}
				],
			},
		)

	async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
		llm = ChatOpenAI(model=model, api_key='test-key', http_client=client, top_p=0.9 if model == 'gpt-6-astra' else None)
		result = await llm.ainvoke([UserMessage(content='Answer ok.')], output_format=Answer if structured else None)

	assert result.completion == (Answer(answer='ok') if structured else '{"answer":"ok"}')
	assert len(requests) == 1
	assert requests[0]['model'] == model
	assert requests[0]['reasoning_effort'] == 'low'
	assert not {'temperature', 'frequency_penalty', 'top_p'} & requests[0].keys()
	assert ('response_format' in requests[0]) is structured


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


@pytest.mark.parametrize('model', ['gpt-5.6-luna', 'gpt-6-astra'])
async def test_current_openai_models_click_button(httpserver, model):
	await run_model_button_click_test(
		model_class=ChatOpenAI,
		model_name=model,
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
