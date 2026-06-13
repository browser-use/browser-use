"""CI tests for browser_use.research.circuit — HostCircuitBreaker ARM layer.

Conventions (CLAUDE.md):
- No mocks — real HostCircuitBreaker, real orchestrator, real asyncio
- No remote URLs — synthetic hosts only
- No @pytest.mark.asyncio decorator needed (pytest-asyncio handles it)
"""

from __future__ import annotations

import asyncio

import pytest

from browser_use.research import (
	CircuitOpenError,
	HostCircuitBreaker,
	ParallelResearchOrchestrator,
)
from browser_use.research.orchestrator import URLNotAllowedError

# ── HostCircuitBreaker — state machine ────────────────────────────────────────


class TestHostCircuitBreakerStateMachine:
	async def test_initial_state_is_closed(self):
		breaker = HostCircuitBreaker(failure_threshold=3, cooldown_seconds=10.0)
		assert breaker.state('https://example.com/page') == 'closed'

	async def test_failures_below_threshold_keep_closed(self):
		breaker = HostCircuitBreaker(failure_threshold=3, cooldown_seconds=10.0)
		url = 'https://flaky.example/api'
		await breaker.record_failure(url)
		await breaker.record_failure(url)
		assert breaker.state(url) == 'closed'
		# allow() should not raise while closed
		await breaker.allow(url)

	async def test_opens_on_threshold(self):
		breaker = HostCircuitBreaker(failure_threshold=3, cooldown_seconds=10.0)
		url = 'https://flaky.example/api'
		for _ in range(3):
			await breaker.record_failure(url)
		assert breaker.state(url) == 'open'

	async def test_open_circuit_blocks_allow(self):
		breaker = HostCircuitBreaker(failure_threshold=2, cooldown_seconds=10.0)
		url = 'https://flaky.example/api'
		await breaker.record_failure(url)
		await breaker.record_failure(url)
		with pytest.raises(CircuitOpenError, match='circuit open'):
			await breaker.allow(url)

	async def test_success_resets_consecutive_counter(self):
		breaker = HostCircuitBreaker(failure_threshold=3, cooldown_seconds=10.0)
		url = 'https://flaky.example/api'
		await breaker.record_failure(url)
		await breaker.record_failure(url)
		await breaker.record_success(url)
		# Counter reset → another two failures should NOT open
		await breaker.record_failure(url)
		await breaker.record_failure(url)
		assert breaker.state(url) == 'closed'

	async def test_cooldown_transitions_to_half_open(self):
		breaker = HostCircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
		url = 'https://flaky.example/api'
		await breaker.record_failure(url)
		await breaker.record_failure(url)
		assert breaker.state(url) == 'open'
		await asyncio.sleep(0.2)
		# allow() during half-open should succeed (transition + pass through)
		await breaker.allow(url)
		assert breaker.state(url) == 'half_open'

	async def test_half_open_success_closes_circuit(self):
		breaker = HostCircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
		url = 'https://flaky.example/api'
		await breaker.record_failure(url)
		await breaker.record_failure(url)
		await asyncio.sleep(0.2)
		await breaker.allow(url)
		await breaker.record_success(url)
		assert breaker.state(url) == 'closed'

	async def test_half_open_failure_reopens_circuit(self):
		breaker = HostCircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
		url = 'https://flaky.example/api'
		await breaker.record_failure(url)
		await breaker.record_failure(url)
		await asyncio.sleep(0.2)
		await breaker.allow(url)  # half_open
		await breaker.record_failure(url)
		assert breaker.state(url) == 'open'
		# And it should block again immediately
		with pytest.raises(CircuitOpenError):
			await breaker.allow(url)

	async def test_hosts_are_isolated(self):
		breaker = HostCircuitBreaker(failure_threshold=2, cooldown_seconds=10.0)
		await breaker.record_failure('https://broken.example/x')
		await breaker.record_failure('https://broken.example/y')
		# broken.example is open; healthy.example is still closed
		assert breaker.state('https://broken.example/anything') == 'open'
		assert breaker.state('https://healthy.example/anything') == 'closed'
		await breaker.allow('https://healthy.example/test')  # does not raise

	async def test_empty_host_is_noop(self):
		breaker = HostCircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
		# urls without a host should silently no-op
		await breaker.record_failure('not-a-url')
		await breaker.allow('not-a-url')  # does not raise


# ── Integration with ParallelResearchOrchestrator ─────────────────────────────


class TestCircuitBreakerInOrchestrator:
	async def test_orchestrator_passes_through_when_closed(self):
		breaker = HostCircuitBreaker(failure_threshold=3, cooldown_seconds=10.0)
		calls: list[str] = []

		async def research_fn(query: str, url: str) -> str:
			calls.append(url)
			return f'content from {url}'

		orch = ParallelResearchOrchestrator(research_fn=research_fn, circuit_breaker=breaker)
		report = await orch.run('q', ['https://a.example/x', 'https://b.example/x'])
		assert report.successful_tabs == 2
		assert len(calls) == 2

	async def test_orchestrator_fail_fast_when_open(self):
		breaker = HostCircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
		# Pre-open the circuit for broken.example
		await breaker.record_failure('https://broken.example/x')
		assert breaker.state('https://broken.example/x') == 'open'

		call_count = 0

		async def research_fn(query: str, url: str) -> str:
			nonlocal call_count
			call_count += 1
			return 'ok'

		orch = ParallelResearchOrchestrator(
			research_fn=research_fn,
			circuit_breaker=breaker,
			max_retries=3,
		)
		report = await orch.run('q', ['https://broken.example/y'])
		# Circuit-open errors are policy: no retries, research_fn never called
		assert call_count == 0
		assert report.successful_tabs == 0
		assert 'circuit open' in (report.tab_results[0].error or '')

	async def test_failures_accumulate_to_open_circuit_mid_run(self):
		# 3 URLs same host, research_fn always fails, threshold=2.
		# First 2 attempts fail and open circuit; third (and any retries) fail fast.
		breaker = HostCircuitBreaker(failure_threshold=2, cooldown_seconds=10.0)
		call_count = 0

		async def research_fn(query: str, url: str) -> str:
			nonlocal call_count
			call_count += 1
			raise RuntimeError('upstream 503')

		orch = ParallelResearchOrchestrator(
			research_fn=research_fn,
			circuit_breaker=breaker,
			max_concurrency=1,  # serialize so the state machine is deterministic
			max_retries=0,
		)
		urls = [f'https://flaky.example/p{i}' for i in range(5)]
		report = await orch.run('q', urls)
		assert report.successful_tabs == 0
		# After 2 failures the circuit opens — the remaining 3 are blocked
		assert call_count == 2
		# All 5 tabs returned a result (errors), none crashed the orchestrator
		assert report.total_tabs == 5

	async def test_recovery_after_cooldown(self):
		breaker = HostCircuitBreaker(failure_threshold=1, cooldown_seconds=0.1)
		await breaker.record_failure('https://x.example/api')
		assert breaker.state('https://x.example/api') == 'open'

		await asyncio.sleep(0.2)

		async def research_fn(query: str, url: str) -> str:
			return 'recovered'

		orch = ParallelResearchOrchestrator(research_fn=research_fn, circuit_breaker=breaker)
		report = await orch.run('q', ['https://x.example/api'])
		assert report.successful_tabs == 1
		assert breaker.state('https://x.example/api') == 'closed'

	async def test_allowlist_violation_still_takes_precedence(self):
		# URLNotAllowedError is policy, raised before circuit breaker is consulted.
		breaker = HostCircuitBreaker(failure_threshold=3, cooldown_seconds=10.0)
		call_count = 0

		async def research_fn(query: str, url: str) -> str:
			nonlocal call_count
			call_count += 1
			return 'ok'

		orch = ParallelResearchOrchestrator(
			research_fn=research_fn,
			circuit_breaker=breaker,
			allowlist=['ok.example'],
		)
		report = await orch.run('q', ['https://blocked.example/x'])
		assert call_count == 0
		assert report.successful_tabs == 0
		assert isinstance(report.tab_results[0].error, str)
		# Circuit shouldn't have been touched for an allowlist reject
		assert breaker.state('https://blocked.example/x') == 'closed'

	async def test_retry_interacts_correctly_with_circuit(self):
		# A retry-able failure should bump the circuit counter on each attempt.
		# threshold=3, max_retries=2 (3 attempts) → circuit opens after the burst.
		breaker = HostCircuitBreaker(failure_threshold=3, cooldown_seconds=10.0)
		call_count = 0

		async def research_fn(query: str, url: str) -> str:
			nonlocal call_count
			call_count += 1
			raise RuntimeError('flaky')

		orch = ParallelResearchOrchestrator(
			research_fn=research_fn,
			circuit_breaker=breaker,
			max_retries=2,
			backoff_base=0.001,
		)
		await orch.run('q', ['https://flaky.example/api'])
		# 3 attempts (initial + 2 retries) all failed → circuit now open
		assert call_count == 3
		assert breaker.state('https://flaky.example/api') == 'open'


# Smoke check: URLNotAllowedError is still importable + works alongside the new module
def test_url_not_allowed_still_exported():
	assert issubclass(URLNotAllowedError, Exception)
