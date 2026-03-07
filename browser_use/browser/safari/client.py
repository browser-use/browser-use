"""Async client for the local Safari companion host."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from .capabilities import DEFAULT_SAFARI_HOST_SOCKET
from .protocol import SafariHostCommandName, SafariHostRequest, SafariHostResponse

T = TypeVar('T', bound=BaseModel)


class SafariHostClient:
	"""JSON-lines client that talks to the local Safari companion over a Unix socket."""

	def __init__(self, socket_path: Path | None = None) -> None:
		self.socket_path = socket_path or Path(os.environ.get('BROWSER_USE_SAFARI_HOST_SOCKET', DEFAULT_SAFARI_HOST_SOCKET))

	async def request(self, command: SafariHostCommandName, params: dict[str, Any] | None = None) -> dict[str, Any]:
		req = SafariHostRequest(command=command, params=params or {})
		reader, writer = await asyncio.open_unix_connection(str(self.socket_path))
		try:
			writer.write((req.model_dump_json() + '\n').encode('utf-8'))
			await writer.drain()
			line = await reader.readline()
			if not line:
				raise RuntimeError('Safari companion host closed the socket without a response')

			response = SafariHostResponse.model_validate_json(line.decode('utf-8'))
			if not response.ok:
				raise RuntimeError(response.error or f'Safari host command failed: {command}')
			return response.result
		finally:
			writer.close()
			await writer.wait_closed()

	async def request_model(
		self,
		command: SafariHostCommandName,
		model: type[T],
		params: dict[str, Any] | None = None,
	) -> T:
		return model.model_validate(await self.request(command, params=params))
