"""Async client for the local Safari companion host."""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from .capabilities import DEFAULT_SAFARI_HOST_SOCKET
from .protocol import SafariHostCommandName, SafariHostRequest, SafariHostResponse

T = TypeVar('T', bound=BaseModel)
DEFAULT_SAFARI_HOST_REQUEST_TIMEOUT_SECONDS = 10.0


class SafariHostClient:
	"""JSON-lines client that talks to the local Safari companion over a Unix socket."""

	def __init__(
		self, socket_path: Path | None = None, request_timeout: float = DEFAULT_SAFARI_HOST_REQUEST_TIMEOUT_SECONDS
	) -> None:
		self.socket_path = socket_path or Path(os.environ.get('BROWSER_USE_SAFARI_HOST_SOCKET', DEFAULT_SAFARI_HOST_SOCKET))
		self.request_timeout = request_timeout

	async def _await_with_timeout(self, awaitable: Any, phase: str) -> Any:
		try:
			return await asyncio.wait_for(awaitable, timeout=self.request_timeout)
		except TimeoutError as exc:
			raise RuntimeError(f'Safari companion host timed out while {phase} after {self.request_timeout:.2f}s') from exc

	async def request(self, command: SafariHostCommandName, params: dict[str, Any] | None = None) -> dict[str, Any]:
		req = SafariHostRequest(command=command, params=params or {})
		reader, writer = await self._await_with_timeout(
			asyncio.open_unix_connection(str(self.socket_path)),
			'opening the socket',
		)
		try:
			writer.write((req.model_dump_json() + '\n').encode('utf-8'))
			await self._await_with_timeout(writer.drain(), 'sending the request')
			line = await self._await_with_timeout(reader.readline(), 'waiting for a response')
			if not line:
				raise RuntimeError('Safari companion host closed the socket without a response')

			response = SafariHostResponse.model_validate_json(line.decode('utf-8'))
			if not response.ok:
				raise RuntimeError(response.error or f'Safari host command failed: {command}')
			return response.result
		finally:
			writer.close()
			with contextlib.suppress(Exception):
				await asyncio.wait_for(writer.wait_closed(), timeout=min(self.request_timeout, 1.0))

	async def request_model(
		self,
		command: SafariHostCommandName,
		model: type[T],
		params: dict[str, Any] | None = None,
	) -> T:
		return model.model_validate(await self.request(command, params=params))
