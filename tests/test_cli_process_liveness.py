"""Tests for cross-platform CLI process liveness helpers."""

import ctypes

from browser_use.skill_cli import tunnel, utils


class _FakeKernel32:
	def __init__(self, live_pid: int = 42, handle: int = 1234) -> None:
		self.live_pid = live_pid
		self.handle = handle
		self.open_calls: list[tuple[int, bool, int]] = []
		self.closed_handles: list[int] = []
		self.terminated: list[tuple[int, int]] = []

	def OpenProcess(self, access: int, inherit_handle: bool, pid: int) -> int:
		self.open_calls.append((access, inherit_handle, pid))
		return self.handle if pid == self.live_pid else 0

	def CloseHandle(self, handle: int) -> None:
		self.closed_handles.append(handle)

	def TerminateProcess(self, handle: int, exit_code: int) -> None:
		self.terminated.append((handle, exit_code))


class _FakeWindll:
	def __init__(self, kernel32: _FakeKernel32) -> None:
		self.kernel32 = kernel32


def test_is_process_alive_uses_openprocess_on_windows(monkeypatch):
	kernel32 = _FakeKernel32(live_pid=42)
	monkeypatch.setattr(utils.sys, 'platform', 'win32')
	monkeypatch.setattr(ctypes, 'windll', _FakeWindll(kernel32), raising=False)
	monkeypatch.setattr(utils.os, 'kill', lambda *_args: (_ for _ in ()).throw(AssertionError('os.kill should not run')))

	assert utils.is_process_alive(42) is True
	assert utils.is_process_alive(99) is False
	assert kernel32.open_calls == [
		(0x1000, False, 42),
		(0x1000, False, 99),
	]
	assert kernel32.closed_handles == [1234]


def test_tunnel_process_liveness_delegates_to_shared_helper(monkeypatch):
	seen: list[int] = []

	def fake_is_process_alive(pid: int) -> bool:
		seen.append(pid)
		return pid == 42

	monkeypatch.setattr(utils, 'is_process_alive', fake_is_process_alive)

	assert tunnel._is_process_alive(42) is True
	assert tunnel._is_process_alive(99) is False
	assert seen == [42, 99]


def test_kill_process_uses_terminateprocess_on_windows(monkeypatch):
	kernel32 = _FakeKernel32(live_pid=42)
	alive_results = iter([False])

	monkeypatch.setattr(tunnel.sys, 'platform', 'win32')
	monkeypatch.setattr(ctypes, 'windll', _FakeWindll(kernel32), raising=False)
	monkeypatch.setattr(tunnel, '_is_process_alive', lambda _pid: next(alive_results))
	monkeypatch.setattr(tunnel.os, 'kill', lambda *_args: (_ for _ in ()).throw(AssertionError('os.kill should not run')))

	assert tunnel._kill_process(42) is True
	assert kernel32.open_calls == [(0x0001, False, 42)]
	assert kernel32.terminated == [(1234, 1)]
	assert kernel32.closed_handles == [1234]
