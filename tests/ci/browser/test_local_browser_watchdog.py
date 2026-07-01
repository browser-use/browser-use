import asyncio
import subprocess

import psutil

from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog


async def _raise_subprocess_not_implemented(*args, **kwargs):
	raise NotImplementedError


async def test_start_browser_process_falls_back_to_popen(monkeypatch):
	calls = {}

	class FakePopen:
		pid = 12345

	class FakePsutilProcess:
		def __init__(self, pid):
			self.pid = pid

	def fake_popen(command, **kwargs):
		calls['command'] = command
		calls['stdout'] = kwargs['stdout']
		calls['stderr'] = kwargs['stderr']
		return FakePopen()

	monkeypatch.setattr(asyncio, 'create_subprocess_exec', _raise_subprocess_not_implemented)
	monkeypatch.setattr(subprocess, 'Popen', fake_popen)
	monkeypatch.setattr(psutil, 'Process', FakePsutilProcess)

	process = await LocalBrowserWatchdog._start_browser_process('chrome', ['--remote-debugging-port=9222'])

	assert process.pid == 12345
	assert calls == {
		'command': ['chrome', '--remote-debugging-port=9222'],
		'stdout': subprocess.DEVNULL,
		'stderr': subprocess.DEVNULL,
	}


async def test_run_subprocess_falls_back_to_blocking_run(monkeypatch):
	calls = {}

	def fake_run(command, **kwargs):
		calls['command'] = command
		calls['capture_output'] = kwargs['capture_output']
		calls['timeout'] = kwargs['timeout']
		calls['check'] = kwargs['check']
		return subprocess.CompletedProcess(command, 0, stdout=b'installed', stderr=b'')

	monkeypatch.setattr(asyncio, 'create_subprocess_exec', _raise_subprocess_not_implemented)
	monkeypatch.setattr(subprocess, 'run', fake_run)

	stdout, stderr = await LocalBrowserWatchdog._run_subprocess(['uvx', 'playwright', 'install', 'chromium'], timeout=60.0)

	assert stdout == b'installed'
	assert stderr == b''
	assert calls == {
		'command': ['uvx', 'playwright', 'install', 'chromium'],
		'capture_output': True,
		'timeout': 60.0,
		'check': False,
	}
