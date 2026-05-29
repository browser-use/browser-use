"""ParallelResearchOrchestrator — Kimi-style concurrent multi-tab agent coordination.

Spawns N async Agent tasks in parallel (one per URL or query variant),
collects CitedResults from each, then synthesizes them into a ResearchReport.

The synthesis step is intentionally LLM-agnostic: callers inject their own
`synthesize_fn` or accept the default string concatenation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

from browser_use.research.citation import CitationTracker
from browser_use.research.views import CitedResult, ResearchReport, TabResult

logger = logging.getLogger(__name__)


# Type alias: an async callable that takes a query + URL and returns plain text
ResearchFn = Callable[[str, str], Coroutine[Any, Any, str]]


async def _default_tab_task(
	query: str,
	url: str,
	research_fn: ResearchFn,
	tracker: CitationTracker,
	tab_id: str,
) -> TabResult:
	"""Execute one tab's research and wrap results with citation provenance."""
	start = time.monotonic()
	try:
		raw_text = await research_fn(query, url)
		cited = tracker.cite(content=raw_text, url=url, page_title=url)
		return TabResult(
			tab_id=tab_id,
			query=query,
			url_visited=url,
			cited_results=[cited],
			duration_seconds=round(time.monotonic() - start, 3),
		)
	except Exception as exc:
		logger.warning('Tab %s failed for %s: %s', tab_id, url, exc)
		return TabResult(
			tab_id=tab_id,
			query=query,
			url_visited=url,
			error=str(exc),
			duration_seconds=round(time.monotonic() - start, 3),
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
		synthesize_fn: Callable[[str, list[CitedResult]], str] | None = None,
	) -> None:
		assert max_concurrency >= 1, 'max_concurrency must be ≥ 1'
		self.research_fn = research_fn
		self.max_concurrency = max_concurrency
		# Callers can inject an LLM-powered synthesizer; default is simple concatenation
		self.synthesize_fn: Callable[[str, list[CitedResult]], str] = synthesize_fn or _default_synthesize

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
				)

		logger.info(
			'ParallelResearchOrchestrator: starting %d tabs (concurrency=%d)',
			len(urls),
			self.max_concurrency,
		)
		tab_results = await asyncio.gather(*[bounded_tab(u, i) for i, u in enumerate(urls)])

		successful = [t for t in tab_results if t.error is None]
		all_cited: list[CitedResult] = [cr for t in successful for cr in t.cited_results]

		synthesis = self.synthesize_fn(research_question, all_cited)

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

	Replace with an LLM call for production synthesis (synthesize_fn must be sync;
	wrap async LLM calls with asyncio.run() or extract the text before passing in)::

		def llm_synthesize(q: str, results: list[CitedResult]) -> str:
			context = "\\n---\\n".join(r.content for r in results)
			return asyncio.run(llm.complete(f"Answer '{q}' using:\\n{context}"))
	"""
	if not results:
		return 'No results were retrieved.'
	parts = [f'[{i + 1}] {r.content[:600]}' for i, r in enumerate(results)]
	return f'**{question}**\n\n' + '\n\n'.join(parts)
