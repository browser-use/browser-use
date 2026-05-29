"""Pydantic models for the research module — citation tracking, multi-tab synthesis, streaming traces."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from uuid_extensions import uuid7str


class Citation(BaseModel):
	"""Provenance record for a single extracted data point."""

	model_config = ConfigDict(extra='forbid')

	id: str = Field(default_factory=uuid7str)
	url: str
	page_title: str = ''
	extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
	# SHA-256[:12] of the raw extracted text — lets callers deduplicate identical extracts
	content_fingerprint: str = ''
	# Confidence ∈ [0, 1]: heuristic from content length + element specificity
	confidence: float = Field(default=1.0, ge=0.0, le=1.0)
	# The actual text fragment that supports a claim
	extract: str = ''
	# Optional: CSS selector or element index where the extract was found
	element_ref: str | None = None


class CitedResult(BaseModel):
	"""An action result tagged with one or more provenance citations."""

	model_config = ConfigDict(extra='forbid')

	id: str = Field(default_factory=uuid7str)
	content: str
	citations: list[Citation] = Field(default_factory=list)
	# mirrors ActionResult.is_done for drop-in compatibility
	is_done: bool = False
	success: bool = True
	error: str | None = None

	def primary_citation(self) -> Citation | None:
		"""Highest-confidence citation, or None."""
		return max(self.citations, key=lambda c: c.confidence, default=None)

	def as_markdown(self) -> str:
		"""Render content + inline citations as Markdown."""
		lines = [self.content, '']
		for i, c in enumerate(self.citations, 1):
			ts = c.extracted_at.strftime('%Y-%m-%d %H:%M UTC')
			lines.append(f'[{i}] <{c.url}> — *{c.page_title}* ({ts}, conf={c.confidence:.2f})')
		return '\n'.join(lines)


class TabResult(BaseModel):
	"""Result produced by one browser tab / sub-agent in a parallel research run."""

	model_config = ConfigDict(extra='forbid')

	tab_id: str = Field(default_factory=uuid7str)
	query: str
	url_visited: str
	cited_results: list[CitedResult] = Field(default_factory=list)
	error: str | None = None
	duration_seconds: float = 0.0


class ResearchReport(BaseModel):
	"""Synthesized output from ParallelResearchOrchestrator."""

	model_config = ConfigDict(extra='forbid')

	id: str = Field(default_factory=uuid7str)
	research_question: str
	tab_results: list[TabResult] = Field(default_factory=list)
	synthesis: str = ''  # LLM-generated answer synthesized across all tabs
	all_citations: list[Citation] = Field(default_factory=list)
	created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
	total_tabs: int = 0
	successful_tabs: int = 0

	def as_markdown(self) -> str:
		lines = [f'# Research Report\n\n**Question:** {self.research_question}\n']
		lines.append(f'**Tabs:** {self.successful_tabs}/{self.total_tabs} succeeded\n')
		lines.append('## Synthesis\n')
		lines.append(self.synthesis or '*No synthesis generated.*')
		lines.append('\n## Sources\n')
		for i, c in enumerate(self.all_citations, 1):
			ts = c.extracted_at.strftime('%Y-%m-%d %H:%M UTC')
			lines.append(f'{i}. <{c.url}> — *{c.page_title}* (conf={c.confidence:.2f}, {ts})')
		return '\n'.join(lines)


# ── Streaming Reasoning Traces ────────────────────────────────────────────────

ReasoningEventType = Literal[
	'step_start',
	'thinking',
	'action',
	'action_result',
	'step_end',
	'task_done',
	'error',
]


class ReasoningTrace(BaseModel):
	"""SSE-compatible event emitted during an agent's reasoning loop.

	Designed to be JSON-serializable and streamable via:
	  - asyncio async generators
	  - FastAPI StreamingResponse
	  - plain stdout for CLI inspection
	"""

	model_config = ConfigDict(extra='forbid')

	id: str = Field(default_factory=uuid7str)
	event_type: ReasoningEventType
	step: int
	timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
	# Event-specific payload — kept as Any so callers aren't forced to unpack it
	data: dict[str, Any] = Field(default_factory=dict)

	def to_sse(self) -> str:
		"""Serialize as a Server-Sent Events frame."""
		payload = self.model_dump(mode='json')
		return f'event: {self.event_type}\ndata: {json.dumps(payload)}\n\n'

	def to_json_line(self) -> str:
		"""NDJSON format — one JSON object per line."""
		return json.dumps(self.model_dump(mode='json'))
