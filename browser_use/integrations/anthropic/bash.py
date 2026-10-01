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


async def _drain_bounded(stream: asyncio.StreamReader, limit: int) -> tuple[bytes, bool]:
	chunks: list[bytes] = []
	retained = 0
	truncated = False
	while chunk := await stream.read(64 * 1024):
		remaining = limit - retained
		if remaining > 0:
			kept = chunk[:remaining]
			chunks.append(kept)
			retained += len(kept)
		if len(chunk) > max(remaining, 0):
			truncated = True
	return b''.join(chunks), truncated


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
	process = await asyncio.create_subprocess_exec(
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
		stdout=asyncio.subprocess.PIPE,
		stderr=asyncio.subprocess.STDOUT,
		start_new_session=True,
	)
	assert process.stdout is not None
	drain = asyncio.create_task(_drain_bounded(process.stdout, max_output_bytes))
	timed_out = False
	try:
		await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
	except TimeoutError:
		timed_out = True
		with contextlib.suppress(ProcessLookupError):
			os.killpg(process.pid, signal.SIGKILL)
		await process.wait()
	except asyncio.CancelledError:
		with contextlib.suppress(ProcessLookupError):
			os.killpg(process.pid, signal.SIGKILL)
		await process.wait()
		await drain
		raise
	output, truncated = await drain
	return json.dumps(
		{
			'exit_code': process.returncode,
			'timed_out': timed_out,
			'truncated': truncated,
			'output': output.decode('utf-8', errors='replace'),
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
