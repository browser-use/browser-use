"""Smoke tests for rrss_arm. Real objects, no mocks (CLAUDE.md doctrine)."""

import asyncio
import pytest

from rrss_arm import CircuitOpenError, HostCircuitBreaker, kafca_retry, kafca_timeout


async def test_circuit_opens_after_threshold():
	b = HostCircuitBreaker(failure_threshold=2, cooldown_seconds=10.0)
	url = 'https://example.com/x'
	await b.allow(url)
	assert b.state(url) == 'closed'
	await b.record_failure(url)
	await b.record_failure(url)
	assert b.state(url) == 'open'
	with pytest.raises(CircuitOpenError):
		await b.allow(url)


async def test_circuit_isolates_per_host():
	b = HostCircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
	await b.record_failure('https://bad.example/x')
	assert b.state('https://bad.example/x') == 'open'
	assert b.state('https://good.example/x') == 'closed'
	await b.allow('https://good.example/x')


async def test_circuit_half_open_then_closed_on_success():
	b = HostCircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)
	await b.record_failure('https://h.example/x')
	assert b.state('https://h.example/x') == 'open'
	await asyncio.sleep(0.1)
	await b.allow('https://h.example/x')
	assert b.state('https://h.example/x') == 'half_open'
	await b.record_success('https://h.example/x')
	assert b.state('https://h.example/x') == 'closed'


async def test_kafca_timeout_raises():
	@kafca_timeout(0.05)
	async def slow():
		await asyncio.sleep(0.5)
		return 'never'
	with pytest.raises(asyncio.TimeoutError):
		await slow()


async def test_kafca_retry_succeeds_eventually():
	calls = {'n': 0}

	@kafca_retry(attempts=3, base_delay=0.01)
	async def flaky():
		calls['n'] += 1
		if calls['n'] < 3:
			raise RuntimeError('nope')
		return 'ok'

	assert await flaky() == 'ok'
	assert calls['n'] == 3


async def test_kafca_retry_reraises_after_attempts():
	@kafca_retry(attempts=2, base_delay=0.01)
	async def always_fails():
		raise ValueError('boom')

	with pytest.raises(ValueError, match='boom'):
		await always_fails()
