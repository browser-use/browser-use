"""ChatBrowserUse invoke span carries gen_ai.* usage/cost so Laminar shows tokens and cost."""

import pytest
from lmnr import Laminar
from lmnr.opentelemetry_lib.tracing import TracerWrapper
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel, ValidationError
from pytest_httpserver import HTTPServer

from browser_use.llm.browser_use.chat import ChatBrowserUse
from browser_use.llm.messages import UserMessage

GATEWAY_RESPONSE = {
	'completion': 'done',
	'usage': {
		'prompt_tokens': 1200,
		'prompt_cached_tokens': 800,
		'prompt_cache_creation_tokens': 100,
		'prompt_image_tokens': None,
		'completion_tokens': 50,
		'total_tokens': 1250,
	},
	'cost': {'total': 0.0123, 'input': 0.01, 'output': 0.002, 'cached': 0.0003, 'cache_storage': 0.0},
}


@pytest.fixture
def laminar_spans(httpserver: HTTPServer):
	"""Real Laminar exporting to the local server, plus an in-memory copy of finished spans."""
	httpserver.expect_request('/v1/traces').respond_with_data('')
	Laminar.initialize(
		project_api_key='test',
		base_url='http://localhost',
		http_port=httpserver.port,
		force_http=True,
		disable_batch=True,
		instruments=set(),
		set_global_tracer_provider=False,
	)
	exporter = InMemorySpanExporter()
	provider = TracerWrapper()._tracer_provider
	assert provider is not None
	provider.add_span_processor(SimpleSpanProcessor(exporter))
	yield exporter
	Laminar.shutdown()


def _invoke_span(exporter: InMemorySpanExporter) -> dict:
	spans = [span for span in exporter.get_finished_spans() if span.name == 'chat_browser_use_ainvoke']
	assert len(spans) == 1
	return dict(spans[0].attributes or {})


async def test_invoke_span_is_llm_span_with_usage_and_cost(httpserver: HTTPServer, laminar_spans: InMemorySpanExporter):
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_json(GATEWAY_RESPONSE)
	llm = ChatBrowserUse(api_key='test-key', base_url=httpserver.url_for('').rstrip('/'))

	result = await llm.ainvoke([UserMessage(content='hi')])

	assert result.completion == 'done'
	assert result.usage is not None and result.usage.prompt_tokens == 1200
	attrs = _invoke_span(laminar_spans)
	assert attrs['lmnr.span.type'] == 'LLM'
	assert attrs['gen_ai.system'] == 'browser-use'
	assert attrs['gen_ai.request.model'] == 'bu-2-0'
	assert attrs['gen_ai.usage.input_tokens'] == 1200
	assert attrs['gen_ai.usage.output_tokens'] == 50
	assert attrs['llm.usage.total_tokens'] == 1250
	assert attrs['gen_ai.usage.cache_read_input_tokens'] == 800
	assert attrs['gen_ai.usage.cache_creation_input_tokens'] == 100
	assert attrs['gen_ai.usage.cost'] == 0.0123


class _Answer(BaseModel):
	answer: int


async def test_invoke_span_keeps_billed_usage_when_completion_fails_validation(
	httpserver: HTTPServer, laminar_spans: InMemorySpanExporter
):
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_json(
		{**GATEWAY_RESPONSE, 'completion': {'answer': 'not a number'}}
	)
	llm = ChatBrowserUse(api_key='test-key', base_url=httpserver.url_for('').rstrip('/'))

	with pytest.raises(ValidationError):
		await llm.ainvoke([UserMessage(content='hi')], output_format=_Answer)

	attrs = _invoke_span(laminar_spans)
	assert attrs['gen_ai.usage.input_tokens'] == 1200
	assert attrs['gen_ai.usage.cost'] == 0.0123


async def test_invoke_span_without_usage_or_cost_sets_only_model(httpserver: HTTPServer, laminar_spans: InMemorySpanExporter):
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_json({'completion': 'done', 'usage': None})
	llm = ChatBrowserUse(model='openai/gpt-5.5', api_key='test-key', base_url=httpserver.url_for('').rstrip('/'))

	result = await llm.ainvoke([UserMessage(content='hi')])

	assert result.usage is None
	attrs = _invoke_span(laminar_spans)
	assert attrs['lmnr.span.type'] == 'LLM'
	assert attrs['gen_ai.request.model'] == 'openai/gpt-5.5'
	assert not any(key.startswith(('gen_ai.usage.', 'llm.usage.')) for key in attrs)


async def test_invoke_without_laminar_initialized_is_unchanged(httpserver: HTTPServer):
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_json(GATEWAY_RESPONSE)
	llm = ChatBrowserUse(api_key='test-key', base_url=httpserver.url_for('').rstrip('/'))

	assert not Laminar.is_initialized()
	result = await llm.ainvoke([UserMessage(content='hi')])

	assert result.completion == 'done'
	assert result.usage is not None and result.usage.total_tokens == 1250
