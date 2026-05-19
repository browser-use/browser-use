"""Tests for daemon Unix socket file permissions.

The HMAC auth token gates command dispatch, but the socket file itself is left
world-accessible by `asyncio.start_unix_server`. On multi-user hosts that lets
a hostile co-tenant `connect()` and probe behavior even before the handshake
fails. The fix is to `chmod 0o600` the socket file right after bind, mirroring
the auth-token file's permissions.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

import pytest

from browser_use.skill_cli.daemon import Daemon

skip_on_windows = pytest.mark.skipif(
	sys.platform == 'win32',
	reason='Daemon uses TCP, not Unix sockets, on Windows.',
)


@skip_on_windows
async def test_daemon_unix_socket_file_is_0o600(monkeypatch: pytest.MonkeyPatch) -> None:
	"""After bind, the Unix socket file must have permissions 0o600 (owner rw only)."""
	# AF_UNIX paths are capped at ~104 bytes on macOS / ~108 on Linux, so the
	# default pytest tmp_path (deep folders/...) is too long. Use a short /tmp dir.
	short_home = Path(tempfile.mkdtemp(prefix='bu-perm-', dir='/tmp'))
	monkeypatch.setenv('BROWSER_USE_HOME', str(short_home))

	daemon = Daemon(headed=False, profile=None, session='perm_test')

	run_task = asyncio.create_task(daemon.run())

	from browser_use.skill_cli.utils import get_socket_path

	sock_path = Path(get_socket_path('perm_test'))
	# Wait for the daemon to bind. start_unix_server creates the file; the chmod
	# (after the fix) runs immediately after.
	for _ in range(100):
		if sock_path.exists():
			break
		if run_task.done():
			# Surface any exception that killed run() before the bind.
			exc = run_task.exception()
			if exc:
				raise AssertionError(f'daemon.run() exited before binding socket: {exc!r}') from exc
			pytest.fail('daemon.run() returned cleanly before binding socket')
		await asyncio.sleep(0.1)
	else:
		run_task.cancel()
		pytest.fail(f'daemon never created socket at {sock_path}')

	try:
		mode = stat.S_IMODE(os.stat(sock_path).st_mode)
		assert mode == 0o600, (
			f'Socket file at {sock_path} has mode {oct(mode)}, expected 0o600. '
			f'World/group access lets co-tenants probe the daemon before the auth handshake.'
		)
	finally:
		daemon._shutdown_event.set()
		try:
			await asyncio.wait_for(run_task, timeout=5)
		except (TimeoutError, asyncio.CancelledError):
			run_task.cancel()
			try:
				await run_task
			except (asyncio.CancelledError, Exception):
				pass
		shutil.rmtree(short_home, ignore_errors=True)
