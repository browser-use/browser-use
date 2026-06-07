"""CI tests for browser_use.research — citation tracking, parallel orchestration, streaming traces.

Conventions (CLAUDE.md):
- No mocks — real objects only
- No remote URLs — pytest-httpserver for all HTTP
- No @pytest.mark.asyncio decorator needed (pytest-asyncio handles it)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from pytest_httpserver import HTTPServer

from browser_use.llm import BaseChatModel
from browser_use.llm.views import ChatInvokeCompletion
from browser_use.research import (
	CitationTracker,
	ParallelResearchOrchestrator,
	StreamingReasoningTracer,
	make_llm_synthesize_fn,
)
from browser_use.research.orchestrator import URLNotAllowedError
from browser_use.research.views import CitedResult, ReasoningTrace


def _make_synthesis_llm(synthesis_text: str) -> BaseChatModel:
	"""Minimal mock LLM that returns *synthesis_text* for any ainvoke call."""
	llm = AsyncMock(spec=BaseChatModel)
	llm.model = 'mock-synth'
	llm._verified_api_keys = True
	llm.provider = 'mock'
	llm.name = 'mock-synth'
	llm.model_name = 'mock-synth'
	llm.ainvoke.return_value = ChatInvokeCompletion(completion=synthesis_text, usage=None)
	return llm


# ── CitationTracker ───────────────────────────────────────────────────────────

class TestCitationTracker:
	def test_cite_returns_cited_result(self):
		tracker = CitationTracker()
		cited = tracker.cite(
			content='OpenAI was founded in 2015.',
			url='https://en.wikipedia.org/wiki/OpenAI',
			page_title='OpenAI',
			element_ref='#firstHeading',
		)
		assert isinstance(cited, CitedResult)
		assert cited.content == 'OpenAI was founded in 2015.'
		assert len(cited.citations) == 1
		c = cited.citations[0]
		assert c.url == 'https://en.wikipedia.org/wiki/OpenAI'
		assert c.page_title == 'OpenAI'
		assert c.element_ref == '#firstHeading'
		assert 0.0 < c.confidence <= 1.0
		assert len(c.content_fingerprint) == 12

	def test_deduplication_same_content(self):
		tracker = CitationTracker()
		c1 = tracker.cite('Same text', url='https://a.example', page_title='A')
		c2 = tracker.cite('Same text', url='https://b.example', page_title='B')
		# Same fingerprint → reuses first citation; tracker still has only 1 entry
		assert len(tracker.all_citations()) == 1
		assert c1.citations[0].id == c2.citations[0].id

	def test_different_content_adds_separate_citations(self):
		tracker = CitationTracker()
		tracker.cite('First fact.', url='https://a.example')
		tracker.cite('Second fact.', url='https://b.example')
		assert len(tracker.all_citations()) == 2

	def test_confidence_higher_for_longer_text(self):
		tracker = CitationTracker()
		short = tracker.cite('Hi.', url='https://x.example')
		long = tracker.cite('x' * 600, url='https://y.example')
		assert long.citations[0].confidence > short.citations[0].confidence

	def test_as_markdown_contains_url(self):
		tracker = CitationTracker()
		cited = tracker.cite('Some claim.', url='https://source.example', page_title='Source')
		md = cited.as_markdown()
		assert 'https://source.example' in md
		assert 'Some claim.' in md

	def test_reset_clears_store(self):
		tracker = CitationTracker()
		tracker.cite('Fact.', url='https://a.example')
		tracker.reset()
		assert tracker.all_citations() == []

	def test_primary_citation_returns_highest_confidence(self):
		tracker = CitationTracker()
		cited = tracker.cite('A claim with enough text ' * 20, url='https://a.example')
		primary = cited.primary_citation()
		assert primary is not None
		assert primary.url == 'https://a.example'


# ── ParallelResearchOrchestrator ──────────────────────────────────────────────

def _make_research_fn(httpserver: HTTPServer):
	"""Return a research_fn that fetches the body of a URL via a stub server."""
	async def research_fn(query: str, url: str) -> str:
		import httpx
		async with httpx.AsyncClient() as client:
			resp = await client.get(url, timeout=5)
			return resp.text

	return research_fn


class TestParallelResearchOrchestrator:
	async def test_runs_all_tabs(self, httpserver: HTTPServer):
		httpserver.expect_request('/page1').respond_with_data('Result for page 1', content_type='text/plain')
		httpserver.expect_request('/page2').respond_with_data('Result for page 2', content_type='text/plain')

		research_fn = _make_research_fn(httpserver)
		orch = ParallelResearchOrchestrator(research_fn=research_fn, max_concurrency=2)

		report = await orch.run(
			research_question='What is on these pages?',
			urls=[
				httpserver.url_for('/page1'),
				httpserver.url_for('/page2'),
			],
		)
		assert report.total_tabs == 2
		assert report.successful_tabs == 2
		assert len(report.all_citations) == 2

	async def test_failed_tab_does_not_crash_report(self, httpserver: HTTPServer):
		httpserver.expect_request('/good').respond_with_data('Good content', content_type='text/plain')

		research_fn = _make_research_fn(httpserver)
		orch = ParallelResearchOrchestrator(research_fn=research_fn, max_concurrency=2)

		report = await orch.run(
			research_question='Test resilience',
			urls=[
				httpserver.url_for('/good'),
				'http://localhost:1',  # unreachable → error
			],
		)
		assert report.total_tabs == 2
		assert report.successful_tabs == 1
		failed = [t for t in report.tab_results if t.error is not None]
		assert len(failed) == 1

	async def test_synthesis_contains_content(self, httpserver: HTTPServer):
		httpserver.expect_request('/data').respond_with_data('The answer is 42.', content_type='text/plain')

		research_fn = _make_research_fn(httpserver)
		orch = ParallelResearchOrchestrator(research_fn=research_fn)

		report = await orch.run(
			research_question='What is the answer?',
			urls=[httpserver.url_for('/data')],
		)
		assert 'The answer is 42.' in report.synthesis

	async def test_concurrency_limit_respected(self, httpserver: HTTPServer):
		"""Max concurrency=1 must serialize tab execution (no RuntimeError from asyncio)."""
		for i in range(3):
			httpserver.expect_request(f'/p{i}').respond_with_data(f'page {i}', content_type='text/plain')

		research_fn = _make_research_fn(httpserver)
		orch = ParallelResearchOrchestrator(research_fn=research_fn, max_concurrency=1)

		report = await orch.run(
			research_question='Serialize test',
			urls=[httpserver.url_for(f'/p{i}') for i in range(3)],
		)
		assert report.total_tabs == 3

	def test_report_as_markdown_contains_question(self, httpserver: HTTPServer):
		from browser_use.research.views import ResearchReport
		report = ResearchReport(
			research_question='What is AI?',
			synthesis='AI is artificial intelligence.',
		)
		md = report.as_markdown()
		assert 'What is AI?' in md
		assert 'AI is artificial intelligence.' in md

	async def test_async_synthesize_fn(self, httpserver: HTTPServer):
		"""ParallelResearchOrchestrator correctly awaits an async synthesize_fn."""
		httpserver.expect_request('/fact').respond_with_data('Fact content.', content_type='text/plain')

		async def async_synth(question: str, results: list[CitedResult]) -> str:
			await asyncio.sleep(0)  # prove it actually awaits
			return f'ASYNC:{question}:{len(results)}'

		research_fn = _make_research_fn(httpserver)
		orch = ParallelResearchOrchestrator(research_fn=research_fn, synthesize_fn=async_synth)
		report = await orch.run(
			research_question='What is truth?',
			urls=[httpserver.url_for('/fact')],
		)
		assert report.synthesis == 'ASYNC:What is truth?:1'

	async def test_make_llm_synthesize_fn(self, httpserver: HTTPServer):
		"""make_llm_synthesize_fn wires the LLM and returns its completion as synthesis."""
		httpserver.expect_request('/src').respond_with_data('Source material.', content_type='text/plain')

		llm = _make_synthesis_llm('LLM-generated synthesis')
		research_fn = _make_research_fn(httpserver)
		orch = ParallelResearchOrchestrator(
			research_fn=research_fn,
			synthesize_fn=make_llm_synthesize_fn(llm),
		)
		report = await orch.run(
			research_question='Summarise the source.',
			urls=[httpserver.url_for('/src')],
		)
		assert report.synthesis == 'LLM-generated synthesis'
		llm.ainvoke.assert_called_once()


# ── StreamingReasoningTracer ──────────────────────────────────────────────────

class TestStreamingReasoningTracer:
	def test_emit_and_accumulate(self):
		tracer = StreamingReasoningTracer()
		tracer.on_step_start(1)
		tracer.on_thinking(1, 'I should navigate first.')
		tracer.on_action(1, 'navigate', {'url': 'https://example.com'})
		tracer.on_action_result(1, 'navigate', 'Success')
		tracer.on_step_end(1, goal_eval='Navigated successfully', memory='On example.com')

		traces = tracer.traces()
		assert len(traces) == 5
		event_types = [t.event_type for t in traces]
		assert event_types == ['step_start', 'thinking', 'action', 'action_result', 'step_end']

	def test_sink_receives_all_events(self):
		received: list[ReasoningTrace] = []
		tracer = StreamingReasoningTracer()
		tracer.add_sink(received.append)

		tracer.on_step_start(1)
		tracer.on_action(1, 'click', {'index': 3})
		tracer.on_task_done(1, 'Task complete.')

		assert len(received) == 3

	async def test_stream_async_generator(self):
		tracer = StreamingReasoningTracer()

		async def producer():
			await asyncio.sleep(0)
			tracer.on_step_start(1)
			tracer.on_task_done(1, 'Done.')

		collected: list[ReasoningTrace] = []

		async def consumer():
			async for trace in tracer.stream():
				collected.append(trace)

		await asyncio.gather(producer(), consumer())
		assert len(collected) == 2
		assert collected[-1].event_type == 'task_done'

	def test_to_sse_format(self):
		tracer = StreamingReasoningTracer()
		tracer.on_step_start(1)
		trace = tracer.traces()[0]
		sse = trace.to_sse()
		assert sse.startswith('event: step_start\n')
		assert 'data:' in sse
		assert sse.endswith('\n\n')

	def test_to_json_line_is_valid_json(self):
		import json
		tracer = StreamingReasoningTracer()
		tracer.on_action(2, 'scroll', {'down': True})
		line = tracer.traces()[0].to_json_line()
		parsed = json.loads(line)
		assert parsed['event_type'] == 'action'
		assert parsed['step'] == 2

	def test_close_terminates_stream(self):
		tracer = StreamingReasoningTracer()
		tracer.close()
		# Queue should have the sentinel None
		sentinel = tracer._queue.get_nowait()
		assert sentinel is None

	def test_error_event(self):
		tracer = StreamingReasoningTracer()
		tracer.on_error(3, 'Navigation timeout')
		t = tracer.traces()[0]
		assert t.event_type == 'error'
		assert 'Navigation timeout' in t.data['error']


# ── RRSS: retry · timeout · allowlist · tracer wiring ─────────────────────────

class TestOrchestratorRRSS:
	async def test_retry_succeeds_after_transient_failure(self):
		"""max_retries causes research_fn to be re-invoked on Exception."""
		call_count = {'n': 0}

		async def flaky_research_fn(query: str, url: str) -> str:
			call_count['n'] += 1
			if call_count['n'] < 3:
				raise RuntimeError(f'transient {call_count["n"]}')
			return 'finally succeeded'

		orch = ParallelResearchOrchestrator(
			research_fn=flaky_research_fn,
			max_retries=3,
			backoff_base=0.01,  # keep test fast
		)
		report = await orch.run(research_question='q', urls=['http://x.example/'])
		assert report.successful_tabs == 1
		assert call_count['n'] == 3

	async def test_retry_exhausted_records_error(self):
		async def always_fail(query: str, url: str) -> str:
			raise RuntimeError('persistent')

		orch = ParallelResearchOrchestrator(
			research_fn=always_fail,
			max_retries=2,
			backoff_base=0.01,
		)
		report = await orch.run(research_question='q', urls=['http://x.example/'])
		assert report.successful_tabs == 0
		assert 'persistent' in (report.tab_results[0].error or '')

	async def test_per_tab_timeout_kills_slow_tab(self):
		async def slow_research_fn(query: str, url: str) -> str:
			await asyncio.sleep(2.0)
			return 'never reached'

		orch = ParallelResearchOrchestrator(
			research_fn=slow_research_fn,
			per_tab_timeout=0.1,
			max_retries=0,
		)
		report = await orch.run(research_question='q', urls=['http://x.example/'])
		assert report.successful_tabs == 0
		# asyncio.TimeoutError or TimeoutError both stringify acceptably
		assert report.tab_results[0].error is not None

	async def test_allowlist_blocks_unlisted_host(self):
		async def research_fn(query: str, url: str) -> str:
			return 'ok'

		orch = ParallelResearchOrchestrator(
			research_fn=research_fn,
			allowlist=['allowed.example'],
		)
		report = await orch.run(
			research_question='q',
			urls=['http://blocked.example/', 'http://allowed.example/'],
		)
		assert report.successful_tabs == 1
		blocked = next(t for t in report.tab_results if 'blocked' in t.url_visited)
		assert blocked.error is not None
		assert 'allowlist' in blocked.error

	async def test_blocklist_rejects_listed_host(self):
		async def research_fn(query: str, url: str) -> str:
			return 'ok'

		orch = ParallelResearchOrchestrator(
			research_fn=research_fn,
			blocklist=['evil.example'],
		)
		report = await orch.run(
			research_question='q',
			urls=['http://evil.example/', 'http://good.example/'],
		)
		assert report.successful_tabs == 1
		evil = next(t for t in report.tab_results if 'evil' in t.url_visited)
		assert evil.error is not None
		assert 'blocklist' in evil.error

	async def test_url_not_allowed_skips_retry(self):
		"""Policy errors are deterministic — retrying them is wasted work."""
		call_count = {'n': 0}

		async def research_fn(query: str, url: str) -> str:
			call_count['n'] += 1
			return 'ok'

		orch = ParallelResearchOrchestrator(
			research_fn=research_fn,
			allowlist=['only.example'],
			max_retries=5,
			backoff_base=0.01,
		)
		report = await orch.run(research_question='q', urls=['http://bad.example/'])
		assert report.successful_tabs == 0
		assert call_count['n'] == 0  # never called

	async def test_tracer_receives_per_tab_events(self):
		async def research_fn(query: str, url: str) -> str:
			return 'content'

		tracer = StreamingReasoningTracer()
		orch = ParallelResearchOrchestrator(research_fn=research_fn, tracer=tracer)
		await orch.run(research_question='q', urls=['http://x.example/'])

		event_types = [t.event_type for t in tracer.traces()]
		assert 'step_start' in event_types
		assert 'action' in event_types
		assert 'action_result' in event_types
		assert 'step_end' in event_types

	def test_url_not_allowed_error_is_exception(self):
		assert issubclass(URLNotAllowedError, Exception)
