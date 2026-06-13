"""ParallelResearchOrchestrator — Kimi-style concurrent multi-tab agent coordination.

Spawns N async Agent tasks in parallel (one per URL or query variant),
collects CitedResults from each, then synthesizes them into a ResearchReport.

The synthesis step is intentionally LLM-agnostic: callers inject their own
`synthesize_fn` or accept the default string concatenation.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from browser_use.research.circuit import CircuitOpenError, HostCircuitBreaker
from browser_use.research.citation import CitationTracker
from browser_use.research.streaming import StreamingReasoningTracer
from browser_use.research.views import CitedResult, ResearchReport, TabResult

logger = logging.getLogger(__name__)


# Type alias: an async callable that takes a query + URL and returns plain text
ResearchFn = Callable[[str, str], Coroutine[Any, Any, str]]

# synthesize_fn can be sync OR async — _call_synthesize handles both
SynthesizeFn = Callable[[str, list[CitedResult]], str] | Callable[[str, list[CitedResult]], Awaitable[str]]


class URLNotAllowedError(Exception):
	"""Raised when a URL is rejected by the orchestrator's allowlist/blocklist."""


def _check_url_allowed(url: str, allowlist: list[str] | None, blocklist: list[str] | None) -> None:
	"""Raise URLNotAllowedError if url violates the configured policy.

	Allowlist takes precedence: if set, only URLs whose host contains one of its
	substrings are accepted. Blocklist rejects URLs whose host contains any entry.
	Substring match keeps the policy simple — wildcards live in your config, not here.
	"""
	from urllib.parse import urlparse

	host = (urlparse(url).hostname or '').lower()
	if allowlist:
		if not any(entry.lower() in host for entry in allowlist):
			raise URLNotAllowedError(f'{url}: host {host!r} not in allowlist')
	if blocklist:
		hit = next((entry for entry in blocklist if entry.lower() in host), None)
		if hit:
			raise URLNotAllowedError(f'{url}: host {host!r} matches blocklist entry {hit!r}')


async def _call_synthesize(
	fn: Callable[[str, list[CitedResult]], Any],
	question: str,
	results: list[CitedResult],
) -> str:
	"""Call *fn* regardless of whether it is sync or async."""
	result = fn(question, results)
	if inspect.isawaitable(result):
		return await result
	return result  # type: ignore[return-value]


def make_llm_synthesize_fn(
	llm: Any,  # BaseChatModel — typed as Any to avoid hard coupling
	system_prompt: str | None = None,
	max_content_chars: int = 800,
) -> Callable[[str, list[CitedResult]], Coroutine[Any, Any, str]]:
	"""Return an async synthesize_fn backed by *llm*.

	Drop in as ``synthesize_fn`` on :class:`ParallelResearchOrchestrator`::

		from browser_use.llm.anthropic import ChatAnthropic
		from browser_use.research import ParallelResearchOrchestrator, make_llm_synthesize_fn

		llm = ChatAnthropic(model='claude-opus-4-7')
		orch = ParallelResearchOrchestrator(
			research_fn=my_research_fn,
			synthesize_fn=make_llm_synthesize_fn(llm),
		)
	"""
	from browser_use.llm.messages import SystemMessage, UserMessage

	_system = system_prompt or (
		'You are a research synthesis engine. '
		'Produce a concise, citation-grounded answer to the question. '
		'Ground every claim in the provided sources.'
	)

	async def _synthesize(question: str, results: list[CitedResult]) -> str:
		if not results:
			return 'No results were retrieved.'
		context_parts = [
			f'[{i + 1}] Source: {c.citations[0].url if c.citations else "unknown"}\n{c.content[:max_content_chars]}'
			for i, c in enumerate(results)
		]
		context = '\n\n---\n\n'.join(context_parts)
		messages = [
			SystemMessage(content=_system),
			UserMessage(content=f'Research question: {question}\n\nSources:\n\n{context}\n\nAnswer:'),
		]
		completion = await llm.ainvoke(messages)
		return completion.completion

	return _synthesize


async def _run_research_with_retry(
	research_fn: ResearchFn,
	query: str,
	url: str,
	max_retries: int,
	backoff_base: float,
	per_tab_timeout: float | None,
	circuit_breaker: HostCircuitBreaker | None = None,
) -> str:
	"""Call research_fn with exponential backoff on transient failure.

	Each attempt is wrapped in asyncio.wait_for if per_tab_timeout is set.
	Retries on any Exception except URLNotAllowedError and CircuitOpenError
	(both are policy decisions, not transient failures).
	"""
	last_exc: Exception | None = None
	for attempt in range(max_retries + 1):
		try:
			if circuit_breaker is not None:
				await circuit_breaker.allow(url)
			if per_tab_timeout is not None:
				result = await asyncio.wait_for(research_fn(query, url), timeout=per_tab_timeout)
			else:
				result = await research_fn(query, url)
			if circuit_breaker is not None:
				await circuit_breaker.record_success(url)
			return result
		except (URLNotAllowedError, CircuitOpenError):
			raise
		except Exception as exc:
			last_exc = exc
			if circuit_breaker is not None:
				await circuit_breaker.record_failure(url)
			if attempt < max_retries:
				delay = backoff_base * (2**attempt)
				logger.info('Retry %d/%d for %s after %.2fs (%s)', attempt + 1, max_retries, url, delay, exc)
				await asyncio.sleep(delay)
	assert last_exc is not None  # unreachable: loop always sets it before exit
	raise last_exc


async def _default_tab_task(
	query: str,
	url: str,
	research_fn: ResearchFn,
	tracker: CitationTracker,
	tab_id: str,
	*,
	max_retries: int = 0,
	backoff_base: float = 0.5,
	per_tab_timeout: float | None = None,
	allowlist: list[str] | None = None,
	blocklist: list[str] | None = None,
	tracer: StreamingReasoningTracer | None = None,
	circuit_breaker: HostCircuitBreaker | None = None,
) -> TabResult:
	"""Execute one tab's research and wrap results with citation provenance."""
	start = time.monotonic()
	step_idx = int(tab_id.rsplit('-', 1)[-1]) if '-' in tab_id else 0
	if tracer:
		tracer.on_step_start(step_idx, state=f'tab={tab_id} url={url}')
		tracer.on_action(step_idx, 'research', {'url': url, 'query': query})
	try:
		_check_url_allowed(url, allowlist, blocklist)
		raw_text = await _run_research_with_retry(
			research_fn, query, url, max_retries, backoff_base, per_tab_timeout, circuit_breaker
		)
		cited = tracker.cite(content=raw_text, url=url, page_title=url)
		duration = round(time.monotonic() - start, 3)
		if tracer:
			tracer.on_action_result(step_idx, 'research', f'{len(raw_text)} chars in {duration}s')
			tracer.on_step_end(step_idx, goal_eval='tab ok', memory=tab_id)
		return TabResult(
			tab_id=tab_id,
			query=query,
			url_visited=url,
			cited_results=[cited],
			duration_seconds=duration,
		)
	except Exception as exc:
		duration = round(time.monotonic() - start, 3)
		logger.warning('Tab %s failed for %s: %s', tab_id, url, exc)
		if tracer:
			tracer.on_error(step_idx, str(exc))
		return TabResult(
			tab_id=tab_id,
			query=query,
			url_visited=url,
			error=str(exc),
			duration_seconds=duration,
		)


class ParallelResearchOrchestrator:
	"""Runs multiple browser-agent tasks in parallel and synthesizes the results.

	Example::

		async def my_research(query: str, url: str) -> str:
			agent = Agent(task=f"{query} on {url}", llm=llm, browser=Browser())
			result = await agent.run()
			return result.final_result() or ''

		orch = ParallelResearchOrchestrator(research_fn=my_research, max_concurrency=4)
		report = await orch.run(
			research_question="What are the latest AI agent benchmarks?",
			urls=["https://arxiv.org", "https://paperswithcode.com"],
		)
		print(report.as_markdown())
	"""

	def __init__(
		self,
		research_fn: ResearchFn,
		max_concurrency: int = 4,
		synthesize_fn: SynthesizeFn | None = None,
		*,
		max_retries: int = 0,
		backoff_base: float = 0.5,
		per_tab_timeout: float | None = None,
		allowlist: list[str] | None = None,
		blocklist: list[str] | None = None,
		tracer: StreamingReasoningTracer | None = None,
		circuit_breaker: HostCircuitBreaker | None = None,
	) -> None:
		assert max_concurrency >= 1, 'max_concurrency must be ≥ 1'
		assert max_retries >= 0, 'max_retries must be ≥ 0'
		assert backoff_base >= 0, 'backoff_base must be ≥ 0'
		assert per_tab_timeout is None or per_tab_timeout > 0, 'per_tab_timeout must be positive'
		self.research_fn = research_fn
		self.max_concurrency = max_concurrency
		# Callers can inject an LLM-powered synthesizer (sync or async); default is simple concatenation
		self.synthesize_fn: SynthesizeFn = synthesize_fn or _default_synthesize
		# Resilience knobs — all opt-in to preserve existing behavior
		self.max_retries = max_retries
		self.backoff_base = backoff_base
		self.per_tab_timeout = per_tab_timeout
		# Security policy — substring match against url host
		self.allowlist = allowlist
		self.blocklist = blocklist
		# Optional tracer — receives one step per tab + a synthesis step
		self.tracer = tracer
		# Optional ARM (Adaptive Rate Management) — per-host failure isolation
		self.circuit_breaker = circuit_breaker

	async def run(self, research_question: str, urls: list[str]) -> ResearchReport:
		"""Run all URLs in parallel (up to max_concurrency at a time)."""
		assert urls, 'urls list must not be empty'
		tracker = CitationTracker()
		semaphore = asyncio.Semaphore(self.max_concurrency)

		async def bounded_tab(url: str, idx: int) -> TabResult:
			tab_id = f'tab-{idx:03d}'
			async with semaphore:
				return await _default_tab_task(
					query=research_question,
					url=url,
					research_fn=self.research_fn,
					tracker=tracker,
					tab_id=tab_id,
					max_retries=self.max_retries,
					backoff_base=self.backoff_base,
					per_tab_timeout=self.per_tab_timeout,
					allowlist=self.allowlist,
					blocklist=self.blocklist,
					tracer=self.tracer,
					circuit_breaker=self.circuit_breaker,
				)

		logger.info(
			'ParallelResearchOrchestrator: starting %d tabs (concurrency=%d)',
			len(urls),
			self.max_concurrency,
		)
		tab_results = await asyncio.gather(*[bounded_tab(u, i) for i, u in enumerate(urls)])

		successful = [t for t in tab_results if t.error is None]
		all_cited: list[CitedResult] = [cr for t in successful for cr in t.cited_results]

		synthesis = await _call_synthesize(self.synthesize_fn, research_question, all_cited)

		report = ResearchReport(
			research_question=research_question,
			tab_results=list(tab_results),
			synthesis=synthesis,
			all_citations=tracker.all_citations(),
			total_tabs=len(tab_results),
			successful_tabs=len(successful),
		)
		logger.info(
			'ParallelResearchOrchestrator: done — %d/%d tabs succeeded',
			report.successful_tabs,
			report.total_tabs,
		)
		return report


def _default_synthesize(question: str, results: list[CitedResult]) -> str:
	"""Concatenate all cited results into a plain-text answer.

	For LLM-powered synthesis use :func:`make_llm_synthesize_fn`; both sync and
	async callables are accepted as ``synthesize_fn``.
	"""
	if not results:
		return 'No results were retrieved.'
	parts = [f'[{i + 1}] {r.content[:600]}' for i, r in enumerate(results)]
	return f'**{question}**\n\n' + '\n\n'.join(parts)
