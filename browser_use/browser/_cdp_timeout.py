"""Per-CDP-request timeout wrapper around cdp_use.CDPClient.

cdp_use's `send_raw()` awaits a future that only resolves when the browser
sends a matching response. If the server goes silent mid-session (observed
failure mode against remote cloud browsers: WebSocket stays "alive" at the
TCP/keepalive layer while the browser container is dead or the proxy has
lost its upstream) the future never resolves and the whole agent hangs.

This module provides a subclass that caps each `send_raw()` request and
removes its pending future when a request times out or is cancelled. Any CDP
method that doesn't get a response within the cap raises `TimeoutError`, which
propagates through existing error-handling paths in browser-use instead of
hanging indefinitely.

Configure the cap via:
- `BROWSER_USE_CDP_TIMEOUT_S` env var (process-wide default)
- `TimeoutWrappedCDPClient(..., cdp_request_timeout_s=...)` constructor arg

Default (60s) is generous for slow operations like `Page.captureScreenshot`
or `Page.printToPDF` on heavy pages, but well below the 180s agent step
timeout and the typical outer agent watchdog.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from typing import Any

from cdp_use import CDPClient

logger = logging.getLogger(__name__)

_CDP_TIMEOUT_FALLBACK_S = 60.0


def _parse_env_cdp_timeout(raw: str | None) -> float:
	"""Parse BROWSER_USE_CDP_TIMEOUT_S defensively.

	Accepts only finite positive values; everything else falls back to the
	hardcoded default with a warning. Mirrors the guard on
	BROWSER_USE_ACTION_TIMEOUT_S in tools/service.py — a bad env value here
	would otherwise make every CDP call time out immediately (nan) or never
	(inf / negative / zero).
	"""
	if raw is None or raw == '':
		return _CDP_TIMEOUT_FALLBACK_S
	try:
		parsed = float(raw)
	except ValueError:
		logger.warning(
			'Invalid BROWSER_USE_CDP_TIMEOUT_S=%r; falling back to %.0fs',
			raw,
			_CDP_TIMEOUT_FALLBACK_S,
		)
		return _CDP_TIMEOUT_FALLBACK_S
	if not math.isfinite(parsed) or parsed <= 0:
		logger.warning(
			'BROWSER_USE_CDP_TIMEOUT_S=%r is not a finite positive number; falling back to %.0fs',
			raw,
			_CDP_TIMEOUT_FALLBACK_S,
		)
		return _CDP_TIMEOUT_FALLBACK_S
	return parsed


DEFAULT_CDP_REQUEST_TIMEOUT_S: float = _parse_env_cdp_timeout(os.getenv('BROWSER_USE_CDP_TIMEOUT_S'))


def _coerce_valid_timeout(value: float | None) -> float:
	"""Normalize a user-supplied timeout to a finite positive value.

	None / nan / inf / non-positive values all fall back to the env-derived
	default with a warning. This mirrors _parse_env_cdp_timeout so callers that
	pass cdp_request_timeout_s directly get the same defensive behaviour as
	callers that set the env var.
	"""
	if value is None:
		return DEFAULT_CDP_REQUEST_TIMEOUT_S
	if not math.isfinite(value) or value <= 0:
		logger.warning(
			'cdp_request_timeout_s=%r is not a finite positive number; falling back to %.0fs',
			value,
			DEFAULT_CDP_REQUEST_TIMEOUT_S,
		)
		return DEFAULT_CDP_REQUEST_TIMEOUT_S
	return float(value)


class TimeoutWrappedCDPClient(CDPClient):
	"""CDPClient subclass that enforces a per-request timeout on send_raw.

	Any CDP method that doesn't receive a response within `cdp_request_timeout_s`
	raises `TimeoutError` instead of hanging forever. Timed out and cancelled
	requests are removed from cdp_use's pending-request map.
	"""

	def __init__(
		self,
		*args: Any,
		cdp_request_timeout_s: float | None = None,
		**kwargs: Any,
	) -> None:
		super().__init__(*args, **kwargs)
		self._cdp_request_timeout_s: float = _coerce_valid_timeout(cdp_request_timeout_s)

	async def send_raw(
		self,
		method: str,
		params: Any | None = None,
		session_id: str | None = None,
	) -> dict[str, Any]:
		websocket = self.ws
		if websocket is None:
			raise RuntimeError('Client is not started. Call start() first or use as async context manager.')

		self.msg_id += 1
		request_id = int(self.msg_id)
		message = {'id': request_id, 'method': method, 'params': params or {}}
		if session_id:
			message['sessionId'] = session_id

		future = asyncio.get_running_loop().create_future()
		self.pending_requests[request_id] = future

		async def send_and_wait() -> dict[str, Any]:
			await websocket.send(json.dumps(message))
			return await future

		try:
			return await asyncio.wait_for(
				send_and_wait(),
				timeout=self._cdp_request_timeout_s,
			)
		except TimeoutError as e:
			# Raise a plain TimeoutError so existing `except TimeoutError`
			# handlers in browser-use / tools treat this uniformly.
			raise TimeoutError(
				f'CDP method {method!r} did not respond within {self._cdp_request_timeout_s:.0f}s. '
				f'The browser may be unresponsive (silent WebSocket — container crashed or proxy lost upstream).'
			) from e
		finally:
			# cdp_use's response handler removes completed IDs, but its send_raw
			# leaves the mapping behind when its wait is cancelled or times out.
			# Remove only this request so late responses cannot grow stale entries.
			if self.pending_requests.get(request_id) is future:
				self.pending_requests.pop(request_id, None)
			if not future.done():
				future.cancel()
