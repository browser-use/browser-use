"""Controlled local teardown regressions that also run without Chromium on Windows CI."""

import asyncio
from unittest.mock import Mock

import psutil
import pytest

from browser_use.browser.events import BrowserKillEvent, BrowserLaunchEvent, BrowserStopEvent
from browser_use.browser.session import BrowserSession, ResilientEventBus
from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog


async def test_launch_preserves_unknown_descendant_snapshot(monkeypatch, tmp_path):
	session = BrowserSession(keep_alive=True, user_data_dir=str(tmp_path))
	watchdog = LocalBrowserWatchdog(event_bus=session.event_bus, browser_session=session)
	process = Mock(spec=psutil.Process)

	async def launch_browser():
		return process, 'http://localhost:9222'

	async def snapshot_descendants(process):
		return None

	monkeypatch.setattr(watchdog, '_launch_browser', launch_browser)
	monkeypatch.setattr(watchdog, '_snapshot_descendants', snapshot_descendants)
	await watchdog.on_BrowserLaunchEvent(BrowserLaunchEvent())
	assert watchdog._subprocess_descendants == []
	assert not watchdog._subprocess_descendants_complete


async def test_cleanup_reports_unknown_descendant_snapshot(monkeypatch):
	root = Mock(spec=psutil.Process)
	root.pid = 41
	root.children.return_value = []
	monkeypatch.setattr(psutil, 'wait_procs', Mock(return_value=([root], [])))
	with pytest.raises(RuntimeError, match='descendant snapshot was unavailable'):
		await LocalBrowserWatchdog._cleanup_process(root, [], descendant_snapshot_complete=False)
	root.terminate.assert_called_once()


async def test_stop_merges_new_descendants_with_launch_snapshot(monkeypatch, tmp_path):
	session = BrowserSession(keep_alive=False, user_data_dir=str(tmp_path))
	watchdog = LocalBrowserWatchdog(event_bus=session.event_bus, browser_session=session)
	root = Mock(spec=psutil.Process)
	orphan = Mock(spec=psutil.Process)
	new_child = Mock(spec=psutil.Process)
	orphan.pid = 42
	new_child.pid = 43
	watchdog._subprocess = root
	watchdog._subprocess_descendants = [orphan]
	watchdog._subprocess_descendants_complete = False
	monkeypatch.setattr(session.event_bus, 'dispatch', Mock())

	async def snapshot_descendants(process):
		return [new_child]

	monkeypatch.setattr(watchdog, '_snapshot_descendants', snapshot_descendants)
	await watchdog.on_BrowserStopEvent(BrowserStopEvent(force=True))
	assert [process.pid for process in watchdog._subprocess_descendants] == [42, 43]
	assert watchdog._subprocess_descendants_complete


async def test_stop_snapshot_failure_still_cleans_known_orphan(monkeypatch, tmp_path):
	session = BrowserSession(keep_alive=False, user_data_dir=str(tmp_path))
	watchdog = LocalBrowserWatchdog(event_bus=session.event_bus, browser_session=session)
	root = Mock(spec=psutil.Process)
	orphan = Mock(spec=psutil.Process)
	root.pid = 41
	orphan.pid = 42
	root.children.side_effect = psutil.NoSuchProcess(pid=41)
	root.terminate.side_effect = psutil.NoSuchProcess(pid=41)
	watchdog._subprocess = root
	watchdog._subprocess_descendants = [orphan]
	monkeypatch.setattr(session.event_bus, 'dispatch', Mock())

	async def snapshot_descendants(process):
		return None

	monkeypatch.setattr(watchdog, '_snapshot_descendants', snapshot_descendants)
	monkeypatch.setattr(psutil, 'wait_procs', Mock(side_effect=[([root], [orphan]), ([orphan], [])]))
	await watchdog.on_BrowserStopEvent(BrowserStopEvent(force=True))
	assert [process.pid for process in watchdog._subprocess_descendants] == [42]
	assert not watchdog._subprocess_descendants_complete
	with pytest.raises(RuntimeError, match='descendant snapshot was unavailable'):
		await watchdog.on_BrowserKillEvent(BrowserKillEvent())
	orphan.terminate.assert_called_once()
	orphan.kill.assert_called_once()
	assert watchdog._subprocess is root
	assert watchdog._subprocess_descendants == [orphan]
	assert not watchdog._subprocess_descendants_complete


async def test_kill_finishes_local_cleanup_before_stopping_event_bus(monkeypatch, tmp_path):
	session = BrowserSession(keep_alive=True, user_data_dir=str(tmp_path))
	watchdog = LocalBrowserWatchdog(event_bus=session.event_bus, browser_session=session)
	watchdog._subprocess = Mock(spec=psutil.Process)
	watchdog._subprocess.children.return_value = []
	watchdog.attach_to_session()
	cleanup_finished = False
	cleanup_at_bus_stop = []
	stop_handler_finished = False
	original_stop = ResilientEventBus.stop

	async def later_stop_handler(event):
		nonlocal stop_handler_finished
		stop_handler_finished = True

	session.event_bus.on(BrowserStopEvent, later_stop_handler)

	async def cleanup(process, known_descendants=None, descendant_snapshot_complete=True):
		nonlocal cleanup_finished
		assert stop_handler_finished
		await asyncio.sleep(0.02)
		cleanup_finished = True

	async def stop(bus, *args, **kwargs):
		cleanup_at_bus_stop.append(cleanup_finished)
		await original_stop(bus, *args, **kwargs)

	monkeypatch.setattr(LocalBrowserWatchdog, '_cleanup_process', staticmethod(cleanup))
	monkeypatch.setattr(ResilientEventBus, 'stop', stop)
	await session.kill()
	assert cleanup_at_bus_stop == [True]
	assert watchdog._subprocess is None


async def test_cleanup_terminates_children_even_when_root_exits_first(monkeypatch):
	root = Mock(spec=psutil.Process)
	child = Mock(spec=psutil.Process)
	root.pid = 41
	child.pid = 42
	root.children.side_effect = psutil.NoSuchProcess(pid=41)
	root.terminate.side_effect = psutil.NoSuchProcess(pid=41)
	monkeypatch.setattr(psutil, 'wait_procs', Mock(return_value=([root, child], [])))
	await LocalBrowserWatchdog._cleanup_process(root, [child])
	root.children.assert_called_once_with(recursive=True)
	child.terminate.assert_called_once()
	root.terminate.assert_called_once()


async def test_nonforce_stop_preserves_keep_alive_process(monkeypatch, tmp_path):
	session = BrowserSession(keep_alive=True, user_data_dir=str(tmp_path))
	watchdog = LocalBrowserWatchdog(event_bus=session.event_bus, browser_session=session)
	watchdog._subprocess = Mock(spec=psutil.Process)
	watchdog.attach_to_session()
	cleaned = []

	async def cleanup(process, known_descendants=None, descendant_snapshot_complete=True):
		cleaned.append(process)

	monkeypatch.setattr(LocalBrowserWatchdog, '_cleanup_process', staticmethod(cleanup))
	event = session.event_bus.dispatch(BrowserStopEvent(force=False))
	await event
	await session.event_bus.stop(clear=True, timeout=1)
	assert cleaned == []


async def test_cleanup_escalates_surviving_children(monkeypatch):
	root = Mock(spec=psutil.Process)
	child = Mock(spec=psutil.Process)
	root.children.return_value = [child]
	wait = Mock(side_effect=[([root], [child]), ([child], [])])
	monkeypatch.setattr(psutil, 'wait_procs', wait)
	await LocalBrowserWatchdog._cleanup_process(root, [])
	child.kill.assert_called_once()
	root.kill.assert_not_called()
	assert [call.kwargs['timeout'] for call in wait.call_args_list] == [3, 2]


async def test_cleanup_reports_survivors_without_skipping_siblings(monkeypatch):
	root = Mock(spec=psutil.Process)
	child = Mock(spec=psutil.Process)
	child.pid = 42
	root.children.return_value = [child]
	child.terminate.side_effect = psutil.AccessDenied(pid=42)
	child.kill.side_effect = psutil.AccessDenied(pid=42)
	monkeypatch.setattr(psutil, 'wait_procs', Mock(side_effect=[([root], [child]), ([], [child])]))
	with pytest.raises(RuntimeError, match='42'):
		await LocalBrowserWatchdog._cleanup_process(root, [])
	root.terminate.assert_called_once()


async def test_kill_propagates_cleanup_failure(monkeypatch, tmp_path):
	session = BrowserSession(keep_alive=True, user_data_dir=str(tmp_path))
	watchdog = LocalBrowserWatchdog(event_bus=session.event_bus, browser_session=session)
	watchdog._subprocess = Mock(spec=psutil.Process)
	watchdog._subprocess.children.return_value = []
	watchdog.attach_to_session()

	async def cleanup(process, known_descendants=None, descendant_snapshot_complete=True):
		raise RuntimeError('browser tree still alive')

	monkeypatch.setattr(LocalBrowserWatchdog, '_cleanup_process', staticmethod(cleanup))
	try:
		with pytest.raises(RuntimeError, match='browser tree still alive'):
			await session.kill()
		assert watchdog._subprocess is not None
	finally:
		await session.event_bus.stop(clear=True, timeout=1)


async def test_cleanup_accepts_already_exited_root(monkeypatch):
	root = Mock(spec=psutil.Process)
	root.pid = 42
	root.children.side_effect = psutil.NoSuchProcess(pid=42)
	root.terminate.side_effect = psutil.NoSuchProcess(pid=42)
	monkeypatch.setattr(psutil, 'wait_procs', Mock(return_value=([], [])))
	await LocalBrowserWatchdog._cleanup_process(root, [])
	root.terminate.assert_called_once()


async def test_remote_stop_does_not_touch_local_process(monkeypatch, tmp_path):
	session = BrowserSession(cdp_url='http://localhost:9222', user_data_dir=str(tmp_path))
	watchdog = LocalBrowserWatchdog(event_bus=session.event_bus, browser_session=session)
	process = Mock(spec=psutil.Process)
	watchdog._subprocess = process
	await watchdog.on_BrowserStopEvent(BrowserStopEvent(force=True))
	assert watchdog._subprocess is process
	process.children.assert_not_called()


async def test_kill_propagates_cleanup_timeout(monkeypatch, tmp_path):
	monkeypatch.setenv('TIMEOUT_BrowserKillEvent', '0.02')
	session = BrowserSession(keep_alive=True, user_data_dir=str(tmp_path))
	watchdog = LocalBrowserWatchdog(event_bus=session.event_bus, browser_session=session)
	watchdog._subprocess = Mock(spec=psutil.Process)
	watchdog._subprocess.children.return_value = []
	watchdog.attach_to_session()

	async def cleanup(process, known_descendants=None, descendant_snapshot_complete=True):
		await asyncio.Event().wait()

	monkeypatch.setattr(LocalBrowserWatchdog, '_cleanup_process', staticmethod(cleanup))
	try:
		with pytest.raises(TimeoutError):
			await session.kill()
		assert watchdog._subprocess is not None
	finally:
		await session.event_bus.stop(clear=True, timeout=1)
