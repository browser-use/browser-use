"""
Prometheus metrics for browser-use LLM token and cost tracking.

Exposes counters and gauges that are updated on every LLM call.
Start an HTTP metrics endpoint with ``start_metrics_server(port)`` so
that external systems (e.g. Token Efficiency, Prometheus, Grafana) can
scrape ``/metrics``.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
	pass

# ---------------------------------------------------------------------------
# Lazy import guard – prometheus_client is an optional dependency.
# ---------------------------------------------------------------------------
_prometheus_client: object | None = None
_init_lock = threading.Lock()


def _get_prometheus():
	"""Lazily import prometheus_client, returning None if not installed."""
	global _prometheus_client
	if _prometheus_client is not None:
		return _prometheus_client
	with _init_lock:
		if _prometheus_client is not None:
			return _prometheus_client
		try:
			import prometheus_client as pc  # type: ignore[import-untyped]

			_prometheus_client = pc
		except ImportError:
			logger.debug('prometheus_client not installed – metrics collection disabled')
	return _prometheus_client


# ---------------------------------------------------------------------------
# Metric definitions (created once on first use)
# ---------------------------------------------------------------------------
_llm_calls_total = None
_tokens_total = None
_cost_total = None


def _ensure_metrics():
	"""Create metric objects idempotently."""
	global _llm_calls_total, _tokens_total, _cost_total
	if _llm_calls_total is not None:
		return

	pc = _get_prometheus()
	if pc is None:
		return

	_llm_calls_total = pc.Counter(
		'browser_use_llm_calls_total',
		'Total number of LLM invocations.',
		['model'],
	)
	_tokens_total = pc.Counter(
		'browser_use_tokens_total',
		'Total tokens consumed.',
		['model', 'token_type'],  # token_type: prompt | completion
	)
	_cost_total = pc.Counter(
		'browser_use_cost_total',
		'Total estimated cost in USD.',
		['model'],
	)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_llm_call(
	model: str,
	prompt_tokens: int,
	completion_tokens: int,
	cost: float | None = None,
) -> None:
	"""Record a single LLM call into Prometheus metrics.

	Safe to call even when prometheus_client is not installed – the call
	becomes a no-op.
	"""
	_ensure_metrics()
	if _llm_calls_total is None:
		return

	_llm_calls_total.labels(model=model).inc()
	_tokens_total.labels(model=model, token_type='prompt').inc(prompt_tokens)
	_tokens_total.labels(model=model, token_type='completion').inc(completion_tokens)
	if cost is not None and cost > 0:
		_cost_total.labels(model=model).inc(cost)


def start_metrics_server(port: int = 9090) -> threading.Thread | None:
	"""Start a background HTTP server that serves ``/metrics``.

	Returns the Thread object, or None if prometheus_client is not available.
	"""
	pc = _get_prometheus()
	if pc is None:
		logger.warning('prometheus_client not installed – metrics server not started')
		return None

	_ensure_metrics()

	def _serve():
		try:
			pc.start_http_server(port)
			logger.info(f'Prometheus metrics server started on :{port}/metrics')
		except OSError:
			logger.warning(f'Could not start metrics server on port {port} (address already in use)')

	t = threading.Thread(target=_serve, name='prometheus-metrics', daemon=True)
	t.start()
	return t
