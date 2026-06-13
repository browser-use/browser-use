"""HostCircuitBreaker — per-host failure tracking with closed/open/half-open states.

ARM (Adaptive Rate Management) layer for ParallelResearchOrchestrator. After a host
exceeds ``failure_threshold`` consecutive failures, its circuit opens and subsequent
requests fail fast with ``CircuitOpenError`` for ``cooldown_seconds``. The first
request after cooldown enters half-open: success closes the circuit, failure reopens
it for another cooldown window.

State is async-safe via per-host ``asyncio.Lock``. All operations are O(1).

Why per-host rather than global: one flaky upstream shouldn't poison healthy ones.
The orchestrator already runs N tabs in parallel against N URLs; circuit isolation
is the natural complement.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


CircuitState = Literal['closed', 'open', 'half_open']


class CircuitOpenError(Exception):
	"""Raised when a request targets a host whose circuit is currently open."""


@dataclass
class _HostState:
	state: CircuitState = 'closed'
	consecutive_failures: int = 0
	opened_at: float = 0.0
	lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class HostCircuitBreaker:
	"""Track failure rates per host; fail fast when a host's circuit is open.

	Example::

		breaker = HostCircuitBreaker(failure_threshold=3, cooldown_seconds=30.0)
		orch = ParallelResearchOrchestrator(
			research_fn=my_fn,
			circuit_breaker=breaker,
		)
	"""

	def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 30.0) -> None:
		assert failure_threshold >= 1, 'failure_threshold must be ≥ 1'
		assert cooldown_seconds > 0, 'cooldown_seconds must be positive'
		self.failure_threshold = failure_threshold
		self.cooldown_seconds = cooldown_seconds
		self._hosts: dict[str, _HostState] = {}
		self._registry_lock = asyncio.Lock()

	@staticmethod
	def _host_of(url: str) -> str:
		return (urlparse(url).hostname or '').lower()

	async def _get_or_create(self, host: str) -> _HostState:
		# Double-checked locking keeps the hot path lock-free once the host is known.
		if host in self._hosts:
			return self._hosts[host]
		async with self._registry_lock:
			if host not in self._hosts:
				self._hosts[host] = _HostState()
			return self._hosts[host]

	async def allow(self, url: str) -> None:
		"""Raise CircuitOpenError if *url*'s host circuit is open and still in cooldown.

		If cooldown has elapsed, transitions open → half_open and lets the call through
		(the caller's next record_success/record_failure decides whether to close or
		re-open).
		"""
		host = self._host_of(url)
		if not host:
			return
		state = await self._get_or_create(host)
		async with state.lock:
			if state.state == 'open':
				elapsed = time.monotonic() - state.opened_at
				if elapsed < self.cooldown_seconds:
					raise CircuitOpenError(
						f'circuit open for host {host!r}; retry in '
						f'{self.cooldown_seconds - elapsed:.1f}s'
					)
				# Cooldown elapsed — promote to half_open and let this one through.
				state.state = 'half_open'
				logger.info('Circuit half-open for %s (cooldown elapsed)', host)

	async def record_success(self, url: str) -> None:
		host = self._host_of(url)
		if not host:
			return
		state = await self._get_or_create(host)
		async with state.lock:
			if state.state != 'closed':
				logger.info('Circuit closed for %s (success)', host)
			state.state = 'closed'
			state.consecutive_failures = 0
			state.opened_at = 0.0

	async def record_failure(self, url: str) -> None:
		host = self._host_of(url)
		if not host:
			return
		state = await self._get_or_create(host)
		async with state.lock:
			if state.state == 'half_open':
				state.state = 'open'
				state.opened_at = time.monotonic()
				logger.warning('Circuit re-opened for %s (half-open trial failed)', host)
				return
			if state.state != 'closed':
				return  # already open — failures here are noise, don't grow the counter
			state.consecutive_failures += 1
			if state.consecutive_failures >= self.failure_threshold:
				state.state = 'open'
				state.opened_at = time.monotonic()
				logger.warning(
					'Circuit opened for %s after %d consecutive failures',
					host,
					state.consecutive_failures,
				)

	def state(self, url_or_host: str) -> CircuitState:
		"""Inspect current state. Read-only; safe to call without the lock.

		Accepts either a URL (``https://host/path``) or a bare hostname.
		URLs are detected by presence of ``://``; everything else is treated as a host.
		"""
		host = self._host_of(url_or_host) if '://' in url_or_host else url_or_host.lower()
		if host not in self._hosts:
			return 'closed'
		return self._hosts[host].state
