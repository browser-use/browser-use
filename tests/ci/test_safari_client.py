"""Tests for the Safari companion socket client."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from browser_use.browser.safari.client import SafariHostClient


class _PendingReader:
	async def readline(self) -> bytes:
		await asyncio.Event().wait()
		return b''


class _RecordingWriter:
	def __init__(self) -> None:
		self.closed = False
		self.payloads: list[bytes] = []

	def write(self, data: bytes) -> None:
		self.payloads.append(data)

	async def drain(self) -> None:
		return None

	def close(self) -> None:
		self.closed = True

	async def wait_closed(self) -> None:
		return None


@pytest.mark.asyncio
async def test_request_times_out_while_waiting_for_response():
	"""Companion requests should fail fast when the socket stays silent."""
	writer = _RecordingWriter()

	async def fake_open_unix_connection(path: str):
		assert path == str(Path('/tmp/fake-safari.sock'))
		return _PendingReader(), writer

	client = SafariHostClient(socket_path=Path('/tmp/fake-safari.sock'), request_timeout=0.01)

	with patch(
		'browser_use.browser.safari.client.asyncio.open_unix_connection',
		side_effect=fake_open_unix_connection,
	):
		with pytest.raises(RuntimeError, match='timed out while waiting for a response'):
			await client.request('capabilities.get')

	assert writer.closed is True
	assert writer.payloads, 'request should be written before timing out'
