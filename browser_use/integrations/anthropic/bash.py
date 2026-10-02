# pyright: reportCallIssue=false

"""Bounded Bash tool for Anthropic tool runners."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
from pathlib import Path
from typing import Any


class _BashOutput(asyncio.SubprocessProtocol):
	"""Collect bounded output until both the process and its pipes have closed."""

	def __init__(self, limit: int) -> None:
		self.limit = limit
		self.output = bytearray()
		self.truncated = False
		loop = asyncio.get_running_loop()
		self.closed = loop.create_future()
		self.exited = loop.create_future()

	def pipe_data_received(self, fd: int, data: bytes) -> None:
		remaining = self.limit - len(self.output)
		self.output.extend(data[:remaining])
		self.truncated |= len(data) > remaining

	def process_exited(self) -> None:
		if not self.exited.done():
			self.exited.set_result(None)

	def connection_lost(self, exc: Exception | None) -> None:
		if not self.closed.done():
			self.closed.set_result(None)


def _prepare_output_dir(output_dir: str | Path) -> tuple[Path, Path]:
	root = Path(output_dir).expanduser().resolve()
	tmp = root / '.tmp'
	root.mkdir(parents=True, exist_ok=True)
	tmp.mkdir(exist_ok=True)
	return root, tmp


async def run_bash(
	command: str,
	*,
	output_dir: str | Path,
	timeout_seconds: float = 120,
	max_output_bytes: int = 50_000,
) -> str:
	"""Run Bash with a stripped environment, bounded output, and a hard timeout."""
	if os.name != 'posix':
		raise RuntimeError('Browser Use Bash currently requires a POSIX host with /bin/bash.')
	if timeout_seconds <= 0:
		raise ValueError('timeout_seconds must be positive')
	if max_output_bytes <= 0:
		raise ValueError('max_output_bytes must be positive')

	root, tmp = await asyncio.to_thread(_prepare_output_dir, output_dir)
	protocol = _BashOutput(max_output_bytes)
	transport, _ = await asyncio.get_running_loop().subprocess_exec(
		lambda: protocol,
		'/bin/bash',
		'--noprofile',
		'--norc',
		'-c',
		command,
		cwd=root,
		env={
			'HOME': str(root),
			'LANG': 'C.UTF-8',
			'LC_ALL': 'C.UTF-8',
			'PATH': '/usr/local/bin:/usr/bin:/bin',
			'PYTHONNOUSERSITE': '1',
			'TMPDIR': str(tmp),
		},
		stdin=asyncio.subprocess.DEVNULL,
		stdout=asyncio.subprocess.PIPE,
		stderr=asyncio.subprocess.STDOUT,
		start_new_session=True,
	)
	timed_out = False
	try:
		# connection_lost covers the shell AND inherited output pipes.
		await asyncio.wait_for(asyncio.shield(protocol.closed), timeout=timeout_seconds)
	except TimeoutError:
		timed_out = True
	except asyncio.CancelledError:
		with contextlib.suppress(ProcessLookupError):
			os.killpg(transport.get_pid(), signal.SIGKILL)
		raise
	finally:
		if timed_out:
			with contextlib.suppress(ProcessLookupError):
				os.killpg(transport.get_pid(), signal.SIGKILL)
		# Close pipes even if a detached descendant still holds their write end.
		transport.close()
		with contextlib.suppress(TimeoutError):
			await asyncio.wait_for(asyncio.shield(protocol.exited), timeout=1)
	return json.dumps(
		{
			'exit_code': transport.get_returncode(),
			'timed_out': timed_out,
			'truncated': protocol.truncated,
			'output': protocol.output.decode('utf-8', errors='replace'),
		},
		ensure_ascii=False,
	)


def Bash(
	*,
	output_dir: str | Path = 'outputs',
	timeout_seconds: float = 120,
	max_output_bytes: int = 50_000,
) -> Any:
	"""Create a bounded Anthropic Bash tool."""
	from anthropic import beta_async_tool

	@beta_async_tool(
		name='bash',
		description=(
			'Run Bash for local computation and create deliverables in the configured output directory. '
			'Browser actions must use the browser toolset.'
		),
	)
	async def bash(command: str) -> str:
		return await run_bash(
			command,
			output_dir=output_dir,
			timeout_seconds=timeout_seconds,
			max_output_bytes=max_output_bytes,
		)

	return bash
