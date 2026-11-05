"""Browser lifecycle with the Browser Use Cloud HTTP API and the harness daemon mocked. No network, no browser."""

import pytest
from conftest import script

from browser_use import Agent, Browser
from browser_use.browser import browser as browser_mod
from browser_use.exceptions import MissingAPIKeyError


@pytest.fixture
def cloud(monkeypatch):
	"""Records cloud API calls and daemon starts/stops instead of making them."""
	from browser_harness import admin

	calls = []
	n = [0]

	def fake_cloud(path, method='GET', body=None):
		calls.append((method, path, body))
		if method == 'POST' and path == '/browsers':
			n[0] += 1
			return {'id': f'b{n[0]}', 'cdpUrl': f'https://cdp{n[0]}.example.test', 'liveUrl': 'https://live.example.test/x'}
		if 'downloads' in path:
			return {'files': [], 'hasMore': False}
		return {}

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-test-key')
	monkeypatch.setattr(browser_mod, '_cloud', fake_cloud)
	monkeypatch.setattr(browser_mod, '_ws_url', lambda url: 'ws://fake.test/devtools/browser/x')
	monkeypatch.setattr(admin, 'ensure_daemon', lambda *a, **k: calls.append(('daemon', 'start', k.get('name'))))
	monkeypatch.setattr(admin, 'restart_daemon', lambda name=None, **k: calls.append(('daemon', 'stop', name)))
	yield calls
	browser_mod._LIVE.clear()  # never let atexit send a leftover fake browser to the real API


def stops(calls):
	return [path for method, path, body in calls if method == 'PATCH' and body == {'action': 'stop'}]


def test_default_browser_is_cloud_with_us_proxy_and_no_live_view():
	b = Browser()
	assert (b.use_cloud, b.local, b.proxy, b.live_view, b.keep_alive) == (True, False, 'us', False, False)
	assert Browser(local=True).use_cloud is False and Browser(use_cloud=False).local is True
	assert Browser(cdp_url='http://x:9222').use_cloud is False


def test_conflicting_or_0x_browser_options_raise():
	with pytest.raises(ValueError):
		Browser(local=True, use_cloud=True)
	with pytest.raises(TypeError, match='headless'):
		Browser(headless=False)


async def test_run_starts_and_stops_cloud_browser(cloud, tmp_path, capsys):
	model, _ = script(('finish', {'result': 'ok'}))
	browser = Browser()
	result = await Agent('t', model, browser=browser, workspace=tmp_path).run()
	assert result.final_result() == 'ok'
	assert [c[:2] for c in cloud if c[0] == 'POST'] == [('POST', '/browsers')]
	assert cloud[0][2]['proxyCountryCode'] == 'us'
	assert stops(cloud) == ['/browsers/b1'] and browser.name is None
	assert 'live.example.test' not in capsys.readouterr().out  # live view off by default
	assert not browser_mod._LIVE


async def test_keep_alive_leaves_cloud_browser_running(cloud, tmp_path):
	model, _ = script(('finish', {'result': 'ok'}))
	browser = Browser(keep_alive=True)
	agent = Agent('t', model, browser=browser, workspace=tmp_path)
	await agent.run()
	await agent.close()
	assert stops(cloud) == [] and browser in browser_mod._LIVE  # atexit/SIGTERM would still stop it
	await browser.stop()
	assert stops(cloud) == ['/browsers/b1'] and not browser_mod._LIVE


async def test_restarted_browser_is_stopped_again(cloud):
	"""BUP bug: `stopped` never reset, so a browser started a second time was skipped at cleanup (kept billing)."""
	browser = Browser()
	await browser.start()
	await browser.stop()
	await browser.start()
	await browser.stop()
	assert stops(cloud) == ['/browsers/b1', '/browsers/b2']


async def test_start_is_idempotent_while_running(cloud):
	browser = Browser()
	assert await browser.start() == await browser.start()
	assert len([c for c in cloud if c[0] == 'POST']) == 1
	await browser.stop()


def test_atexit_cleanup_stops_live_browsers(cloud):
	import asyncio

	browser = Browser()
	asyncio.run(browser.start())
	browser_mod._stop_all()  # what atexit and the SIGTERM handler run
	assert stops(cloud) == ['/browsers/b1']


@pytest.mark.parametrize(
	'task',
	[
		'Open http://localhost:3000 and check the title',
		'test my app on 127.0.0.1:8000',
		'go to http://192.168.1.20/admin',
		'visit 10.0.0.5',
		'check http://172.20.1.1',
		'open http://[::1]:8080',
		'open printer.local',
	],
)
async def test_localhost_task_with_cloud_browser_raises_before_start(cloud, task):
	model, _ = script()
	with pytest.raises(ValueError, match='Browser\\(local=True\\)'):
		await Agent(task, model).run()
	assert cloud == []


@pytest.mark.parametrize('task', ['find local restaurants', 'compare 10.5 and 10.25', 'version 172.15.0.1'])
def test_localhost_guard_ignores_normal_text(task):
	from browser_use.agent.service import LOCAL_TARGET

	assert not LOCAL_TARGET.search(task)


async def test_missing_key_raises_and_never_falls_back_to_local(cloud, monkeypatch):
	import browser_harness.auth

	monkeypatch.delenv('BROWSER_USE_API_KEY')

	def no_key():
		raise RuntimeError('no key')

	monkeypatch.setattr(browser_harness.auth, 'get_browser_use_api_key', no_key)
	model, _ = script()
	with pytest.raises(MissingAPIKeyError, match='browser-use auth login'):
		await Agent('t', model).run()
	with pytest.raises(MissingAPIKeyError, match='Browser\\(local=True\\)'):
		await Agent('t').run()  # default model too
	assert cloud == []


async def test_live_view_opt_in_prints_url(cloud, monkeypatch, capsys):
	import webbrowser

	opened = []
	monkeypatch.setattr(webbrowser, 'open', lambda url, new=0: opened.append(url))
	browser = Browser(live_view=True)
	await browser.start()
	await browser.stop()
	assert opened == ['https://live.example.test/x'] and 'live.example.test' in capsys.readouterr().out


def test_cdp_host_for_telemetry():
	assert Browser(cdp_url='wss://connect.example.test/x?token=t').cdp_host == 'connect.example.test'
	assert Browser(local=True).cdp_host is None


async def test_cancelled_start_still_stops_the_cloud_browser(cloud, monkeypatch):
	"""Roast C1: cancelling start() during the POST left the created browser untracked (billed, never stopped)."""
	import asyncio
	import threading

	posting, release = threading.Event(), threading.Event()
	real = browser_mod._cloud

	def slow_cloud(path, method='GET', body=None):
		if method == 'POST':
			posting.set()
			release.wait(10)
		return real(path, method, body)

	monkeypatch.setattr(browser_mod, '_cloud', slow_cloud)
	browser = Browser()
	task = asyncio.ensure_future(browser.start())
	await asyncio.to_thread(posting.wait, 10)
	task.cancel()
	threading.Timer(0.2, release.set).start()  # the POST returns after the cancellation
	with pytest.raises(asyncio.CancelledError):
		await task
	assert stops(cloud) == ['/browsers/b1'] and not browser_mod._LIVE


async def test_failed_stop_keeps_the_browser_owned_for_retry(cloud, monkeypatch):
	"""Roast C2: after a failed stop the id and _LIVE entry were dropped, so neither stop() nor atexit could retry."""
	real, fail = browser_mod._cloud, [True]

	def flaky(path, method='GET', body=None):
		if method == 'PATCH' and fail[0]:
			raise RuntimeError('HTTP 502')
		return real(path, method, body)

	monkeypatch.setattr(browser_mod, '_cloud', flaky)
	monkeypatch.setattr(browser_mod.time, 'sleep', lambda s: None)
	browser = Browser()
	await browser.start()
	await browser.stop()
	assert browser in browser_mod._LIVE and browser.id == 'b1' and stops(cloud) == []
	fail[0] = False
	browser_mod._stop_all()  # what atexit runs
	assert stops(cloud) == ['/browsers/b1'] and not browser_mod._LIVE


async def test_concurrent_starts_create_one_browser(cloud):
	"""Roast C4: two concurrent start() calls each created a cloud browser; one leaked."""
	import asyncio

	browser = Browser()
	a, b = await asyncio.gather(browser.start(), browser.start())
	assert a == b and len([c for c in cloud if c[0] == 'POST']) == 1
	await browser.stop()
	assert stops(cloud) == ['/browsers/b1']


async def test_downloads_are_listed_before_the_stop(cloud, tmp_path):
	"""The v4 API lists a session's downloads; ask before the stop PATCH as well as after."""
	browser = Browser()
	await browser.start()
	await browser.stop(downloads_dir=tmp_path)
	order = [c[0] if c[0] == 'PATCH' else 'list' for c in cloud if c[0] == 'PATCH' or 'downloads' in c[1]]
	assert order == ['list', 'PATCH', 'list']


def with_downloads(monkeypatch, files, list_hook=None):
	"""The cloud fake lists `files` ({'path', 'url'}) as the browser's downloads; list_hook runs on every listing."""
	real = browser_mod._cloud

	def fake(path, method='GET', body=None):
		if 'downloads' in path:
			real(path, method, body)  # recorded
			if list_hook:
				list_hook()
			return {'files': files, 'hasMore': False}
		return real(path, method, body)

	monkeypatch.setattr(browser_mod, '_cloud', fake)


async def test_restart_during_stop_waits_and_keeps_the_new_browser_owned(cloud, monkeypatch, tmp_path):
	"""Roast r2-2: a start() during stop()'s post-stop download pass created browser B; the old stop then cleared B's
	id, so B was never stopped (billed until the server timeout)."""
	import asyncio
	import threading

	listing, release, n = threading.Event(), threading.Event(), [0]

	def hook():
		n[0] += 1
		if n[0] == 2:  # the post-stop pass
			listing.set()
			release.wait(10)

	with_downloads(monkeypatch, [], hook)
	browser = Browser()
	await browser.start()
	stopping = asyncio.ensure_future(browser.stop(downloads_dir=tmp_path))
	await asyncio.to_thread(listing.wait, 10)
	starting = asyncio.ensure_future(browser.start())
	await asyncio.sleep(0.1)
	assert len([c for c in cloud if c[0] == 'POST']) == 1  # the restart waits for the whole stop
	release.set()
	await stopping
	await starting
	assert browser.id == 'b2' and browser in browser_mod._LIVE
	await browser.stop()
	assert stops(cloud) == ['/browsers/b1', '/browsers/b2'] and not browser_mod._LIVE


async def test_cancelled_download_collection_still_stops_the_cloud_browser(cloud, monkeypatch, tmp_path):
	"""Roast r2-3: cancelling stop() during the pre-stop download pass skipped the PATCH stop (billing went on)."""
	import asyncio
	import threading

	listing, release = threading.Event(), threading.Event()
	with_downloads(monkeypatch, [], lambda: (listing.set(), release.wait(10)))
	browser = Browser()
	await browser.start()
	task = asyncio.ensure_future(browser.stop(downloads_dir=tmp_path))
	await asyncio.to_thread(listing.wait, 10)
	task.cancel()
	release.set()
	with pytest.raises(asyncio.CancelledError):
		await task
	assert stops(cloud) == ['/browsers/b1'] and not browser_mod._LIVE


async def test_hung_download_never_holds_the_stop(cloud, monkeypatch, tmp_path):
	"""Roast r2-3: download collection had no overall bound; a hung transfer kept the browser billed."""
	import threading
	import time

	release = threading.Event()
	with_downloads(monkeypatch, [{'path': '/dl/a.pdf', 'url': 'https://files.test/a'}])
	monkeypatch.setattr(browser_mod, 'DOWNLOADS_TIMEOUT_S', 0.3)
	monkeypatch.setattr(browser_mod.urllib.request, 'urlopen', lambda *a, **k: release.wait(10))
	browser = Browser()
	await browser.start()
	t = time.monotonic()
	try:
		await browser.stop(downloads_dir=tmp_path)
	finally:
		release.set()
	assert time.monotonic() - t < 3 and stops(cloud) == ['/browsers/b1']


async def test_failed_download_is_retried_after_the_stop(cloud, monkeypatch, tmp_path):
	"""Roast r2-7: a download was marked done before it was copied; one pre-stop connection reset lost the file."""
	import io

	with_downloads(monkeypatch, [{'path': '/dl/report.pdf', 'url': 'https://files.test/r'}])
	attempts = []

	def urlopen(url, timeout=None):
		attempts.append(url)
		if len(attempts) == 1:
			raise ConnectionResetError('reset by peer')
		return io.BytesIO(b'%PDF-1')

	monkeypatch.setattr(browser_mod.urllib.request, 'urlopen', urlopen)
	browser = Browser()
	await browser.start()
	files = await browser.stop(downloads_dir=tmp_path)
	assert files == [tmp_path / 'report.pdf'] and (tmp_path / 'report.pdf').read_bytes() == b'%PDF-1'
	assert len(attempts) == 2


async def test_start_after_a_cancelled_stop_never_overlaps_its_stop_thread(cloud, monkeypatch):
	"""A stop() cancelled during the PATCH leaves its thread running; a start() right after must not run its own
	_stop_now beside it (a second PATCH, and the late thread could disown the new browser)."""
	import asyncio
	import threading

	patching, release = threading.Event(), threading.Event()
	real = browser_mod._cloud

	def fake(path, method='GET', body=None):
		if method == 'PATCH':
			patching.set()
			release.wait(10)
		return real(path, method, body)

	monkeypatch.setattr(browser_mod, '_cloud', fake)
	browser = Browser()
	await browser.start()
	task = asyncio.ensure_future(browser.stop())
	await asyncio.to_thread(patching.wait, 10)
	task.cancel()
	with pytest.raises(asyncio.CancelledError):
		await task
	starting = asyncio.ensure_future(browser.start())
	await asyncio.sleep(0.2)
	assert len([c for c in cloud if c[0] == 'POST']) == 1  # the restart waits for the running stop
	release.set()
	await starting
	assert browser.id == 'b2' and browser in browser_mod._LIVE and stops(cloud) == ['/browsers/b1']
	await browser.stop()
	assert stops(cloud) == ['/browsers/b1', '/browsers/b2'] and not browser_mod._LIVE


async def test_sigterm_during_exit_cleanup_never_deadlocks(cloud, monkeypatch):
	"""SIGTERM while atexit is stopping a browser runs the handler's _stop_all on the thread that already holds the
	stop lock; a non-reentrant lock hung the process forever."""
	import threading

	real, entered = browser_mod._cloud, []

	def fake(path, method='GET', body=None):
		if method == 'PATCH' and not entered:
			entered.append(1)
			browser_mod._stop_all()  # the SIGTERM handler, interrupting this very thread
		return real(path, method, body)

	monkeypatch.setattr(browser_mod, '_cloud', fake)
	browser = Browser()
	await browser.start()
	t = threading.Thread(target=browser_mod._stop_all, daemon=True)  # what atexit runs
	t.start()
	t.join(5)
	assert not t.is_alive() and browser.stopped and not browser_mod._LIVE


async def test_local_start_is_bounded_when_chrome_never_allows_remote_debugging(monkeypatch):
	"""Fable r3-7: Browser(local=True) called ensure_daemon() without a wait; browser-harness then waits forever on
	Chrome's "Allow remote debugging?" prompt, so Agent.run() hung before its timeout even started."""
	from browser_harness import admin

	calls = []

	def ensure_daemon(wait=None, name=None, env=None):  # what browser-harness does once the wait runs out
		calls.append(wait)
		if wait is None:
			raise AssertionError('unbounded wait: would hang forever on the prompt')
		raise RuntimeError("permission-blocked: Chrome's Allow popup is still open and the pending daemon was left running.")

	monkeypatch.setattr(admin, 'ensure_daemon', ensure_daemon)
	with pytest.raises(RuntimeError, match='did not allow remote debugging within 120s'):
		await Browser(local=True).start()
	assert calls == [browser_mod.LOCAL_START_WAIT_S]
