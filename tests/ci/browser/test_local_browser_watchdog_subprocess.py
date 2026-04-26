import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import browser_use.browser.watchdogs.local_browser_watchdog as watchdog_module
from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog


async def test_create_subprocess_exec_uses_asyncio_when_available(monkeypatch):
	mock_create_subprocess = AsyncMock(return_value='async-process')
	monkeypatch.setattr(asyncio, 'create_subprocess_exec', mock_create_subprocess)

	mock_to_thread = AsyncMock()
	monkeypatch.setattr(asyncio, 'to_thread', mock_to_thread)

	fake_watchdog = cast(LocalBrowserWatchdog, SimpleNamespace(logger=MagicMock()))

	result = await LocalBrowserWatchdog._create_subprocess_exec(
		fake_watchdog,
		'chrome.exe',
		'--remote-debugging-port=9222',
		stdout=1,
		stderr=2,
	)

	assert result == 'async-process'
	mock_create_subprocess.assert_awaited_once()
	mock_to_thread.assert_not_awaited()
	fake_watchdog.logger.warning.assert_not_called()


async def test_create_subprocess_exec_falls_back_on_not_implemented(monkeypatch):
	async def _raise_not_implemented(*args, **kwargs):
		raise NotImplementedError

	monkeypatch.setattr(asyncio, 'create_subprocess_exec', _raise_not_implemented)

	fallback_process = object()
	mock_to_thread = AsyncMock(return_value=fallback_process)
	monkeypatch.setattr(asyncio, 'to_thread', mock_to_thread)

	fake_watchdog = cast(LocalBrowserWatchdog, SimpleNamespace(logger=MagicMock()))

	result = await LocalBrowserWatchdog._create_subprocess_exec(
		fake_watchdog,
		'chrome.exe',
		'--remote-debugging-port=9222',
		stdout=1,
		stderr=2,
	)

	assert result is fallback_process
	fake_watchdog.logger.warning.assert_called_once()

	called = mock_to_thread.await_args
	assert called is not None
	assert called.args[0] is watchdog_module.std_subprocess.Popen
	assert called.args[1] == ['chrome.exe', '--remote-debugging-port=9222']
	assert called.kwargs['stdout'] == 1
	assert called.kwargs['stderr'] == 2


async def test_communicate_and_kill_subprocess_handle_sync_processes(monkeypatch):
	class FakePopen:
		def __init__(self):
			self.killed = False
			self.waited = False
			self.running = True

		def communicate(self, timeout: float | None = None):
			return b'stdout', b'stderr'

		def poll(self):
			return None if self.running else 0

		def kill(self):
			self.killed = True
			self.running = False

		def wait(self):
			self.waited = True
			return 0

	monkeypatch.setattr(watchdog_module.std_subprocess, 'Popen', FakePopen)

	async def _run_in_thread(func, *args, **kwargs):
		return func(*args, **kwargs)

	monkeypatch.setattr(asyncio, 'to_thread', _run_in_thread)

	process = FakePopen()

	stdout, stderr = await LocalBrowserWatchdog._communicate_subprocess(process, timeout=10.0)
	assert stdout == b'stdout'
	assert stderr == b'stderr'

	await LocalBrowserWatchdog._kill_subprocess(process)
	assert process.killed is True
	assert process.waited is True
