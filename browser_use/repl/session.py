"""Parent side of the REPL worker (worker.py). Kill-and-restart on timeout; files and the browser survive.

Transport: the worker connects back to a 127.0.0.1 ephemeral port and proves itself with a random token, so it
works the same on Windows, macOS and Linux (no inherited file descriptors).

Secrets: the worker gets an allowlisted environment (no API keys or tokens). sensitive_data values travel over the
control channel, are usable only through type_secret(name), and are replaced with <secret:name> in everything the
worker returns. This limits accidental leaks; it is not a sandbox (model-written Python can still read local files).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import secrets
import sys
from pathlib import Path
from typing import Any

MODES = ('default', 'ultrafast')
STREAM_LIMIT = 256 * 1024 * 1024
ENV_ALLOW = {
	'PATH', 'PATHEXT', 'HOME', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'USER', 'USERNAME', 'LOGNAME', 'SHELL', 'TERM',
	'SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'COMSPEC', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMDATA', 'PROGRAMFILES',
	'TEMP', 'TMP', 'TMPDIR', 'LANG', 'LANGUAGE', 'TZ', 'XDG_CONFIG_HOME', 'XDG_RUNTIME_DIR', 'XDG_CACHE_HOME',
	'DISPLAY', 'WAYLAND_DISPLAY', 'PYTHONPATH', 'PYTHONIOENCODING', 'PYTHONUTF8', 'VIRTUAL_ENV',
}  # fmt: skip
ENV_ALLOW_PREFIXES = ('LC_', 'BU_', 'BH_')  # browser-harness reads BU_NAME, BH_RUNTIME_DIR, BH_TMP_DIR, ...
ENV_DENY = {'BU_CDP_WS', 'BU_CDP_URL', 'BU_MODE'}  # CDP URLs can carry credentials; only Repl.mode sets BU_MODE
SECRET_ENV = re.compile(r'KEY|TOKEN|SECRET|PASSW|CREDENTIAL|AUTH', re.I)


def check_mode(mode: str | None) -> str:
	if mode is None:  # Pi: mode undefined means 'default'
		return 'default'
	if mode not in MODES:
		raise ValueError("mode must be 'default' or 'ultrafast'.")
	return mode


def worker_env(extra: dict[str, str] | None = None) -> dict[str, str]:
	"""The REPL worker's environment: an allowlist of the parent's, never anything that looks like a credential."""
	env = {
		k: v
		for k, v in os.environ.items()
		if (k.upper() in ENV_ALLOW or k.upper().startswith(ENV_ALLOW_PREFIXES))
		and k.upper() not in ENV_DENY
		and not SECRET_ENV.search(k)
	}
	return {**env, **(extra or {})}


def redact(text: Any, values: dict[str, str]) -> Any:
	"""Replace each secret value with <secret:name>, longest first."""
	if not isinstance(text, str):
		return text
	for name, value in sorted(values.items(), key=lambda kv: -len(kv[1])):
		if value:
			text = text.replace(value, f'<secret:{name}>')
	return text


class Repl:
	"""mode='ultrafast' adds the `bu` helpers to the worker (BU_MODE=ultrafast)."""

	def __init__(
		self,
		workspace: Path,
		env: dict[str, str] | None = None,
		mode: str | None = 'default',
		secrets: dict[str, str] | None = None,
	):
		self.workspace, self.env, self.n, self.mode = workspace, env or {}, 0, check_mode(mode)
		self.secrets = dict(secrets or {})
		self.proc: asyncio.subprocess.Process | None = None
		self.state = workspace / '.browser-use'
		self.lock = asyncio.Lock()  # the model may emit parallel python calls; the worker runs one cell at a time

	async def start(self) -> None:
		self.state.mkdir(parents=True, exist_ok=True)
		token = secrets.token_hex(32)
		connected: asyncio.Future = asyncio.get_running_loop().create_future()

		async def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
			try:
				line = await asyncio.wait_for(reader.readline(), 10)
			except Exception:  # - a stray client
				line = b''
			if not connected.done() and hmac.compare_digest(line.strip(), token.encode()):
				connected.set_result((reader, writer))
			else:
				writer.close()

		server = await asyncio.start_server(on_connect, '127.0.0.1', 0, limit=STREAM_LIMIT)
		port = server.sockets[0].getsockname()[1]
		env = worker_env(self.env)
		env.update(BH_TAB_MARKER='0', BU_STATE_DIR=str(self.state), BU_REPL_PORT=str(port), BU_REPL_TOKEN=token)
		if self.mode == 'ultrafast':
			env['BU_MODE'] = 'ultrafast'
		log = open(self.state / 'worker.log', 'ab')  # noqa: ASYNC230 - handed to the child process
		try:
			self.proc = await asyncio.create_subprocess_exec(
				sys.executable,
				'-m',
				'browser_use.repl.worker',
				cwd=self.workspace,
				stdin=asyncio.subprocess.DEVNULL,
				stdout=log,
				stderr=log,
				env=env,
			)
			exited = asyncio.ensure_future(self.proc.wait())
			done, _ = await asyncio.wait({connected, exited}, timeout=60, return_when=asyncio.FIRST_COMPLETED)
			exited.cancel()
			if connected not in done:
				await self.close()
				raise RuntimeError(f'REPL worker failed to start; see {self.state / "worker.log"}')
			self.reader, self.writer = connected.result()
		finally:
			log.close()
			server.close()
		self.writer.write(json.dumps({'secrets': self.secrets}).encode() + b'\n')
		await self.writer.drain()
		ready = await asyncio.wait_for(self.reader.readline(), 60)
		if not ready:
			await self.close()
			raise RuntimeError(f'REPL worker failed to start; see {self.state / "worker.log"}')

	async def close(self) -> None:
		if self.proc and self.proc.returncode is None:
			self.proc.kill()
			await self.proc.wait()
		self.proc = None

	async def call(self, op: str, code: str, timeout: float) -> dict[str, Any]:
		# Ultrafast prints the page state after the cell's code, so its cells may run up to 10 s past the timeout.
		async with self.lock:
			r = await self._call(op, code, timeout + (10 if self.mode == 'ultrafast' else 0))
		return {**r, **{k: redact(r.get(k), self.secrets) for k in ('output', 'error', 'value')}}

	async def _call(self, op: str, code: str, timeout: float) -> dict[str, Any]:
		if self.proc is None or self.proc.returncode is not None:
			await self.start()
		self.n += 1
		self.writer.write(json.dumps({'op': op, 'code': code, 'n': self.n}).encode() + b'\n')
		await self.writer.drain()
		try:
			line = await asyncio.wait_for(self.reader.readline(), timeout)
			if not line:
				raise ConnectionError('worker exited')
			return json.loads(line)
		except (TimeoutError, ConnectionError) as e:
			await self.close()
			out = self.state / 'cells' / f'{self.n:04d}.txt'
			why = f'Cell timed out after {timeout:g}s' if isinstance(e, TimeoutError) else 'REPL worker exited'
			return {
				'output': out.read_text(errors='replace') if out.exists() else '',
				'images': [],
				'output_file': str(out),
				'value': None,
				'error': f'{why}. The REPL restarted: Python variables are lost; files, checkpoints and '
				'browser state survive. Actions may already have happened; inspect before retrying.',
			}
