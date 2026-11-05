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
	return calls


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
