"""browser_use.research — competitive-parity browser-agent research primitives.

Three innovations extracted from Kimi / Perplexity / Grok patterns:

  CitationTracker          — Perplexity-style provenance tagging
  ParallelResearchOrchestrator — Kimi-style concurrent multi-tab coordination
  StreamingReasoningTracer — Grok-style live chain-of-thought emission
"""

from browser_use.research.citation import CitationTracker
from browser_use.research.orchestrator import ParallelResearchOrchestrator
from browser_use.research.streaming import StreamingReasoningTracer
from browser_use.research.views import (
	Citation,
	CitedResult,
	ReasoningTrace,
	ResearchReport,
	TabResult,
)

__all__ = [
	'CitationTracker',
	'ParallelResearchOrchestrator',
	'StreamingReasoningTracer',
	'Citation',
	'CitedResult',
	'ReasoningTrace',
	'ResearchReport',
	'TabResult',
]
