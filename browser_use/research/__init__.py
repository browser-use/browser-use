"""browser_use.research — competitive-parity browser-agent research primitives.

Three innovations extracted from Kimi / Perplexity / Grok patterns:

  CitationTracker          — Perplexity-style provenance tagging
  ParallelResearchOrchestrator — Kimi-style concurrent multi-tab coordination
  StreamingReasoningTracer — Grok-style live chain-of-thought emission
"""

from browser_use.research.circuit import CircuitOpenError, HostCircuitBreaker
from browser_use.research.citation import CitationTracker
from browser_use.research.orchestrator import ParallelResearchOrchestrator, make_llm_synthesize_fn
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
	'CircuitOpenError',
	'HostCircuitBreaker',
	'ParallelResearchOrchestrator',
	'StreamingReasoningTracer',
	'make_llm_synthesize_fn',
	'Citation',
	'CitedResult',
	'ReasoningTrace',
	'ResearchReport',
	'TabResult',
]
