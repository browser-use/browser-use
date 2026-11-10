"""Browser lifecycle with the Browser Use Cloud HTTP API and the harness daemon mocked. No network, no browser."""

import json
import subprocess
import sys

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


def test_browser_kinds_and_their_0x_aliases():
	kinds = [Browser().kind, Browser('cloud').kind, Browser('chromium').kind, Browser('chrome').kind]
	assert kinds == ['cloud', 'cloud', 'chromium', 'chrome']
	assert Browser(local=True).kind == Browser(use_cloud=False).kind == 'chromium'  # fresh local, as 0.x launched
	assert Browser(cdp_url='http://x:9222').kind == 'cdp' and Browser(use_cloud=True).kind == 'cloud'
	assert Browser('chrome', profile='Work', headless=True).chrome_profile == 'Work'


@pytest.mark.parametrize(
	'kwargs, match',
	[
		({'kind': 'firefox'}, "pick 'cloud'"),
		({'kind': 'chrome', 'local': True}, 'Pass one of'),
		({'local': True, 'use_cloud': True}, 'Pass one of'),
		({'kind': 'cloud', 'use_cloud': False}, 'Pass one of'),
		({'kind': 'chromium', 'cdp_url': 'http://x:9222'}, 'Pass one of'),
		({'headless': False}, r'Browser\(\) \(a cloud browser\) does not take headless='),
		({'kind': 'chrome', 'headless': True}, "Browser\\('chromium', ...\\) launches"),
		({'kind': 'chrome', 'executable_path': '/x'}, 'executable_path'),
		({'kind': 'chrome', 'user_data_dir': '/x'}, 'user_data_dir'),
		({'kind': 'chromium', 'profile': 'Work'}, "Browser\\('chrome', profile=...\\)"),
		({'kind': 'chromium', 'cloud_profile_id': 'p'}, 'cloud profiles'),
		({'local': True, 'live_view': True}, 'live view'),
	],
)
def test_browser_options_that_do_not_fit_the_kind_raise_before_start(kwargs, match):
	with pytest.raises(ValueError, match=match):
		Browser(**kwargs)


def test_chromes_default_profile_dir_is_refused_as_user_data_dir():
	"""Chrome 136+ refuses remote debugging on its default user-data-dir; launching on it would fail opaquely."""
	default = browser_mod._local.chrome_user_data_dir()
	with pytest.raises(ValueError, match='Chrome 136'):
		Browser('chromium', user_data_dir=default)


@pytest.mark.parametrize(
	'option, instead',
	[
		('channel', 'executable_path'),
		('window_size', 'Emulation.setDeviceMetricsOverride'),
		# a cloud browser (the default) ignores Network.setUserAgentOverride and device metrics; Emulation's UA works
		('user_agent', 'Emulation.setUserAgentOverride'),
		('viewport', 'a cloud browser keeps its own viewport'),
		('downloads_path', 'agent.workspace/downloads'),
		('record_video_dir', 'result.messages'),
		('highlight_elements', 'highlight_actions=False'),
		('cloud_browser_params', 'cloud_profile_id'),
		('proxy_country_code', 'cloud_proxy_country_code'),
		('args', "Browser('chromium')"),
	],
)
def test_0x_browser_options_name_their_1_0_alternative(option, instead):
	"""M37: 51 of 67 0.x Browser options got a generic "not a 1.0 option" instead of the removed error MIGRATING.md
	promises, with the alternative it lists."""
	with pytest.raises(TypeError, match=rf'^Browser\({option}=\.\.\.\) was removed in browser-use 1\.0\.') as raised:
		Browser(**{option: True})
	assert instead in str(raised.value)


def test_conflicting_or_0x_browser_options_raise():
	with pytest.raises(ValueError):
		Browser(local=True, use_cloud=True)
	with pytest.raises(TypeError, match='window_size'):
		Browser(window_size={'width': 800})
	with pytest.raises(TypeError, match="profile='Profile 1'"):
		Browser(profile_directory='Profile 1')


async def test_run_starts_and_stops_cloud_browser(cloud, tmp_path, capsys):
	model, _ = script(('finish', {'success': True, 'result': 'ok'}))
	browser = Browser()
	result = await Agent('t', model, browser=browser, workspace=tmp_path).run()
	assert result.final_result() == 'ok'
	assert [c[:2] for c in cloud if c[0] == 'POST'] == [('POST', '/browsers')]
	assert cloud[0][2]['proxyCountryCode'] == 'us'
	assert stops(cloud) == ['/browsers/b1'] and browser.name is None
	assert 'live.example.test' not in capsys.readouterr().out  # live view off by default
	assert not browser_mod._LIVE


async def test_keep_alive_leaves_cloud_browser_running(cloud, tmp_path):
	model, _ = script(('finish', {'success': True, 'result': 'ok'}))
	browser = Browser(keep_alive=True)
	agent = Agent('t', model, browser=browser, workspace=tmp_path)
	await agent.run()
	await agent.close()
	assert stops(cloud) == [] and browser in browser_mod._LIVE  # atexit/SIGTERM would still stop it
	await browser.stop()
	assert stops(cloud) == ['/browsers/b1'] and not browser_mod._LIVE


@pytest.mark.parametrize('method', ['kill', 'close'])
async def test_the_0x_kill_and_close_at_the_end_of_a_keep_alive_script_stop_the_browser(cloud, tmp_path, method):
	"""Live (0.x follow-up-tasks template): after both runs, `await browser.kill()` raised AttributeError, so the script
	crashed and its keep_alive cloud browser stayed billed until the process exited. A call made after the browser
	started cannot fail before it, so it stops the browser as stop() does."""
	model, _ = script(('finish', {'success': True, 'result': 'ok'}))
	browser = Browser(keep_alive=True)
	await Agent('t', model, browser=browser, workspace=tmp_path).run()
	assert stops(cloud) == []
	await getattr(browser, method)()
	assert stops(cloud) == ['/browsers/b1'] and not browser_mod._LIVE


async def test_keep_alive_cloud_downloads_land_in_each_runs_workspace(cloud, monkeypatch, tmp_path):
	"""H7: with keep_alive the run skipped the download copy and browser.stop() had no downloads_dir, so the cloud
	browser's downloads were lost. C13: then stop() put every run's files in the last Agent's workspace. Each run now
	copies its own downloads when it ends and lists them in result.downloads; stop() never copies a file twice."""
	import io

	files = [{'path': '/d/report.csv', 'url': 'u1'}]
	with_downloads(monkeypatch, files)
	monkeypatch.setattr(browser_mod.urllib.request, 'urlopen', lambda url, timeout=None, context=None: io.BytesIO(b'data'))
	browser = Browser(keep_alive=True)
	results = []
	for name in ('a', 'b'):
		model, _ = script(('finish', {'success': True, 'result': 'ok'}))
		agent = Agent('t', model, browser=browser, workspace=tmp_path / name)
		results.append(await agent.run())
		await agent.close()
		files.append({'path': '/d/data.pdf', 'url': 'u2'})  # downloaded by the second run
	assert results[0].downloads == [tmp_path / 'a' / 'downloads' / 'report.csv']
	assert results[1].downloads == [tmp_path / 'b' / 'downloads' / 'data.pdf']
	assert (tmp_path / 'a' / 'downloads' / 'report.csv').read_bytes() == b'data'
	assert await browser.stop() == []


async def test_a_socket_path_too_long_for_the_os_names_the_path_before_anything_starts(cloud, monkeypatch, tmp_path):
	"""M40: a long BH_HOME / XDG_CONFIG_HOME failed inside the daemon with "AF_UNIX path too long", naming no path; on
	cloud it showed as "stopped remote browser"."""
	import sys

	from browser_harness import _ipc as ipc

	if sys.platform == 'win32':
		pytest.skip('Windows uses TCP loopback')
	long_dir = tmp_path / ('a' * 120)
	monkeypatch.setattr(ipc, '_sock_path', lambda name: long_dir / f'bu-{name}.sock')
	with pytest.raises(RuntimeError, match=r'socket path is \d+ bytes, over the 10\d-byte limit.*BH_RUNTIME_DIR') as raised:
		await Browser().start()
	assert str(long_dir) in str(raised.value) and '/tmp/bh' not in str(raised.value)  # EXEC-3: a per-user dir
	assert not [c for c in cloud if c[0] == 'POST'] and not browser_mod._LIVE  # no cloud browser created


async def test_a_runtime_dir_other_users_can_write_is_refused_before_anything_starts(cloud, shared_runtime_dir):
	"""EXEC-3: browser-harness keeps the daemon's socket (its only lock on POSIX) in a BH_RUNTIME_DIR that already
	exists, as is: in another user's /tmp/bh they could swap it for a fake daemon and get every CDP command."""
	with pytest.raises(RuntimeError, match=r'is writable by other users \(mode 777\).*chmod 700'):
		await Browser().start()
	with pytest.raises(RuntimeError, match='writable by other users'):
		await Browser('chrome').start()  # the shared default daemon too
	assert not [c for c in cloud if c[0] in ('POST', 'daemon')] and not browser_mod._LIVE


async def test_a_rejected_provider_key_or_unknown_model_never_creates_a_cloud_browser(cloud, monkeypatch, tmp_path):
	"""M3: a bad OpenAI key or an unknown Anthropic model failed only on the first model request, after a cloud browser
	had been created and billed. One free GET of the model on its provider now fails first."""
	import io
	import re
	import urllib.error

	from browser_use import ChatAnthropic, ChatGoogle, ChatOpenAI

	asked = []

	def urlopen(request, timeout=None):
		url = request.full_url if hasattr(request, 'full_url') else request
		asked.append(url)
		if 'api.openai.com/v1/models/gpt-6-luna' in url:
			body = b'{"error": {"message": "Incorrect API key provided", "code": "invalid_api_key"}}'
			raise urllib.error.HTTPError(url, 401, 'Unauthorized', {}, io.BytesIO(body))  # type: ignore[arg-type]
		if re.search(r'generativelanguage\.googleapis\.com/v1\w*/models/gemini-nonexistent-9', url):  # any API version
			raise urllib.error.HTTPError(url, 404, 'Not Found', {}, io.BytesIO(b'{"error": "Model is not found"}'))  # type: ignore[arg-type]
		if 'api.anthropic.com/v1/models/claude-nonexistent-9' in url:
			raise urllib.error.HTTPError(url, 404, 'Not Found', {}, io.BytesIO(b'{"error": "model: claude-nonexistent-9"}'))  # type: ignore[arg-type]
		return io.BytesIO(b'{}')

	monkeypatch.setattr('browser_use.llm.urlopen_keyed', urlopen)
	for var in ('ANTHROPIC_BASE_URL', 'OPENAI_BASE_URL'):  # the official endpoints, whatever this machine points at
		monkeypatch.delenv(var, raising=False)
	for llm, expect in (
		(ChatOpenAI('gpt-6-luna', api_key='sk-invalid'), 'openai rejected the API key (401)'),
		(ChatAnthropic('claude-nonexistent-9', api_key='k'), 'claude-nonexistent-9 is not a model this anthropic key'),
		(ChatGoogle('gemini-nonexistent-9', api_key='k'), 'gemini-nonexistent-9 is not a model this google key'),
	):
		result = await Agent('t', llm, browser=Browser(), workspace=tmp_path).run()
		assert result.status == 'error' and expect in (result.error or ''), result.error
	assert not [c for c in cloud if c[0] == 'POST'] and len(asked) == 3
	model, _ = script(('finish', {'success': True, 'result': 'ok'}))  # a model it cannot check: runs as before
	assert (await Agent('t', model, browser=Browser(), workspace=tmp_path).run()).final_result() == 'ok'


def test_preflight_fails_only_on_a_bad_key_or_model_and_only_asks_google_itself(monkeypatch):
	"""Review: Google's 400 API_KEY_INVALID passed (browser created and billed); a key that may run the model but not
	look it up (OpenAI 401 missing scope, Anthropic 403) was refused; an auth_token client sent 'x-api-key: None'; a
	Google client pointed at a proxy sent the proxy's key to Google; 'models/gemini-2.5-flash' became
	/models/models/...; an error that quoted the key returned it."""
	import io
	import urllib.error

	from anthropic import AsyncAnthropic
	from google import genai
	from google.genai import types
	from pydantic_ai.models.anthropic import AnthropicModel
	from pydantic_ai.models.google import GoogleModel
	from pydantic_ai.providers.anthropic import AnthropicProvider
	from pydantic_ai.providers.google import GoogleProvider

	from browser_use import ChatAnthropic, ChatGoogle, ChatOpenAI
	from browser_use.llm import provider_preflight, resolve_model

	asked, answers = [], {}

	def urlopen(request, timeout=None):
		asked.append(request.full_url)
		code, body = answers[request.full_url]
		raise urllib.error.HTTPError(request.full_url, code, 'x', {}, io.BytesIO(body.encode()))  # type: ignore[arg-type]

	monkeypatch.setattr('browser_use.llm.urlopen_keyed', urlopen)
	for var in ('ANTHROPIC_BASE_URL', 'OPENAI_BASE_URL'):
		monkeypatch.delenv(var, raising=False)
	version = resolve_model(ChatGoogle('gemini-2.5-flash', api_key='bad'))[0].client._api_client._http_options.api_version
	g = f'https://generativelanguage.googleapis.com/{version}/models/gemini-2.5-flash'
	bad_google = '{"error": {"code": 400, "message": "API key not valid.", "status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}}'
	answers[g] = (400, bad_google)
	assert 'google rejected the API key (400): API key not valid.' in provider_preflight(
		resolve_model(ChatGoogle('gemini-2.5-flash', api_key='bad'))[0]
	)
	prefixed = GoogleModel('models/gemini-2.5-flash', provider=GoogleProvider(api_key='bad'))
	assert 'rejected the API key' in (provider_preflight(prefixed) or '') and asked[-1] == g
	proxy = genai.Client(api_key='proxy-key', http_options=types.HttpOptions(base_url='https://llm-proxy.example.test/'))
	n = len(asked)
	assert provider_preflight(GoogleModel('gemini-2.5-flash', provider=GoogleProvider(client=proxy))) is None
	token = AnthropicModel('claude-haiku-4-5', provider=AnthropicProvider(anthropic_client=AsyncAnthropic(auth_token='t')))
	assert provider_preflight(token) is None and len(asked) == n  # neither asked anyone

	answers['https://api.openai.com/v1/models/gpt-6-luna'] = (
		401,
		'{"error": {"message": "You have insufficient permissions for this operation. Missing scopes: api.model.read.", "code": null}}',
	)
	assert provider_preflight(resolve_model(ChatOpenAI('gpt-6-luna', api_key='sk-restricted'))[0]) is None
	answers['https://api.anthropic.com/v1/models/claude-haiku-4-5'] = (
		403,
		'{"type": "error", "error": {"type": "permission_error", "message": "not allowed"}}',
	)
	assert provider_preflight(resolve_model(ChatAnthropic('claude-haiku-4-5', api_key='k'))[0]) is None
	answers['https://api.openai.com/v1/models/gpt-6-luna'] = (
		401,
		'{"error": {"message": "Incorrect API key provided: sk-quoted-XYZ.", "code": "invalid_api_key"}}',
	)
	error = provider_preflight(resolve_model(ChatOpenAI('gpt-6-luna', api_key='sk-quoted-XYZ'))[0]) or ''
	assert 'openai rejected the API key (401)' in error and 'sk-quoted-XYZ' not in error, error


def test_google_preflight_asks_the_api_version_the_model_runs_on(monkeypatch):
	"""rr-legacy 1: the 0.x quickstart's ChatGoogle('gemini-flash-latest') passed the preflight (it asked v1beta, where
	the model exists), a cloud browser started and was billed, then the first request 404'd on v1, where the client
	ran (google-genai 3, now capped below 3). The preflight asks the version the client sends requests to."""
	import io
	import urllib.error

	from browser_use import ChatGoogle
	from browser_use.llm import provider_preflight, resolve_model

	asked = []

	model = resolve_model(ChatGoogle('gemini-flash-latest', api_key='k'))[0]
	version = model.client._api_client._http_options.api_version

	def urlopen(request, timeout=None):  # the model is on every version except the one the client runs on
		asked.append(request.full_url)
		if f'/{version}/' not in request.full_url:
			return io.BytesIO(b'{}')
		body = f'{{"error": {{"code": 404, "message": "models/gemini-flash-latest is not found for API version {version}"}}}}'
		raise urllib.error.HTTPError(request.full_url, 404, 'x', {}, io.BytesIO(body.encode()))  # type: ignore[arg-type]

	monkeypatch.setattr('browser_use.llm.urlopen_keyed', urlopen)
	assert 'gemini-flash-latest is not a model this google key can use (404)' in (provider_preflight(model) or ''), asked
	assert asked == [f'https://generativelanguage.googleapis.com/{version}/models/gemini-flash-latest']


async def test_a_preflight_error_never_shows_a_secret(cloud, monkeypatch, tmp_path, caplog):
	"""Review: the preflight error went to the log and result.error verbatim, past sensitive_data redaction."""
	from browser_use import ChatOpenAI

	secret = 'hunter2-Zq9-long'
	monkeypatch.setattr(
		'browser_use.agent.service.provider_preflight', lambda model: f'openai rejected the API key (401): {secret}'
	)
	agent = Agent(
		't', ChatOpenAI('gpt-6-luna', api_key='sk-x'), browser=Browser(), workspace=tmp_path, sensitive_data={'pw': secret}
	)
	result = await agent.run()
	assert result.status == 'error' and '<secret:pw>' in (result.error or '')
	assert secret not in (result.error or '') and secret not in caplog.text


def _shape(result):
	"""Everything but the message and the duration."""
	return (result.status, result.text, result.output, result.steps, result.usage, result.cost_usd, result.partial,
		result.messages, result.success, result.downloads)  # fmt: skip


@pytest.mark.parametrize('fails', ['create', 'attach'])
async def test_a_cloud_browser_that_fails_to_start_returns_the_preflight_error_shape(cloud, monkeypatch, tmp_path, fails):
	"""Error contract: a failed cloud create (402 out of credits, 5xx, timeout) or a daemon that could not attach to the
	created (billed) browser raised out of run(), while a preflight failure returns status='error'. Both now return the
	same result shape, the browser is stopped, and run() never raises after a billed browser started."""
	from browser_harness import admin

	from browser_use import ChatOpenAI

	secret = 'hunter2-Zq9-long'
	if fails == 'create':
		fake_cloud = browser_mod._cloud

		def cloud_402(path, method='GET', body=None):
			if method == 'POST' and path == '/browsers':
				raise RuntimeError(f'Browser Use Cloud POST /browsers failed: HTTP 402 out of credits ({secret}).')
			return fake_cloud(path, method, body)

		monkeypatch.setattr(browser_mod, '_cloud', cloud_402)
	else:

		def no_daemon(*a, **k):
			raise RuntimeError(f'daemon could not attach ({secret})')

		monkeypatch.setattr(admin, 'ensure_daemon', no_daemon)
	monkeypatch.setattr('browser_use.agent.service.provider_preflight', lambda model: None)
	llm = ChatOpenAI('gpt-6-luna', api_key='sk-x')
	result = await Agent('t', llm, browser=Browser(), workspace=tmp_path, sensitive_data={'pw': secret}).run()
	assert result.status == 'error' and ('HTTP 402' if fails == 'create' else 'could not attach') in (result.error or '')
	assert secret not in (result.error or '') and '<secret:pw>' in (result.error or '')
	assert stops(cloud) == ([] if fails == 'create' else ['/browsers/b1']) and not browser_mod._LIVE
	monkeypatch.setattr('browser_use.agent.service.provider_preflight', lambda model: 'openai rejected the API key (401)')
	preflight = await Agent('t', llm, browser=Browser(), workspace=tmp_path).run()
	assert _shape(result) == _shape(preflight)


@pytest.mark.parametrize('kind', ['chrome', 'cloud'])
async def test_a_profile_name_that_matches_none_raises_from_run(cloud, monkeypatch, tmp_path, kind):
	"""Review: since a browser that fails to start returns status='error', Browser('chrome', profile='Gaming') and
	Browser(cloud_profile_id='Gaming') naming no profile returned status='error' too, while MIGRATING.md says
	configuration errors raise before any browser starts and a profile name that matches none raises with the list.
	Nothing is launched or created first."""
	from browser_use import ChatOpenAI
	from browser_use.browser import local as _local

	root = tmp_path / 'Chrome'
	(root / 'Default').mkdir(parents=True)
	(root / 'Local State').write_text(json.dumps({'profile': {'info_cache': {'Default': {'name': 'Personal'}}}}))
	monkeypatch.setattr(_local, 'chrome_user_data_dir', lambda: root)
	monkeypatch.setattr(_local, 'find_binary', lambda *a, **k: '/nonexistent/chrome')
	monkeypatch.setattr('browser_use.agent.service.provider_preflight', lambda model: None)
	browser = Browser('chrome', profile='Gaming') if kind == 'chrome' else Browser(cloud_profile_id='Gaming')
	agent = Agent('t', ChatOpenAI('gpt-6-luna', api_key='sk-x'), browser=browser, workspace=tmp_path / 'w')
	with pytest.raises(ValueError, match="No Chrome profiles match 'Gaming'.*'Personal'" if kind == 'chrome' else 'Gaming'):
		await agent.run()
	assert not [c for c in cloud if c[:2] == ('POST', '/browsers')] and not browser_mod._LIVE


async def test_a_reattach_waiting_on_a_stop_never_creates_a_browser(cloud):
	"""Review: reattach() checked that the browser was started before it took the lock; a stop() holding the lock then
	cleared it, and start() created a new cloud browser (billed, none of the agent's tabs)."""
	import asyncio

	browser = Browser()
	await browser.start()
	await browser._lock.acquire()  # a stop() is under way
	reattach = asyncio.ensure_future(browser.reattach())
	await asyncio.sleep(0.05)
	await asyncio.to_thread(browser._stop_now)
	browser._lock.release()
	with pytest.raises(RuntimeError, match='The browser was stopped while the agent ran'):
		await reattach
	assert len([c for c in cloud if c[0] == 'POST']) == 1


async def test_restarted_browser_is_stopped_again(cloud):
	"""BUP bug: `stopped` never reset, so a browser started a second time was skipped at cleanup (kept billing)."""
	browser = Browser()
	await browser.start()
	await browser.stop()
	await browser.start()
	await browser.stop()
	assert stops(cloud) == ['/browsers/b1', '/browsers/b2']


async def test_a_kept_alive_cloud_browser_that_ended_between_runs_is_replaced(cloud, monkeypatch):
	"""Browser(keep_alive=True) in a service: once the cloud browser ended (cloud_timeout, a dashboard stop), every
	later run raised 'The browser is gone' until the code called browser.stop(). The next start now creates a new one;
	a reattach in the middle of a run still raises (a new browser has none of the agent's tabs)."""
	from browser_harness import admin

	def ensure_daemon(name=None, env=None, **k):
		if (env or {}).get('BU_BROWSER_ID') == 'b1' and stopped_b1:
			raise RuntimeError('cdp websocket closed')
		cloud.append(('daemon', 'start', name))

	stopped_b1 = False
	monkeypatch.setattr(admin, 'ensure_daemon', ensure_daemon)
	monkeypatch.setattr(admin, 'daemon_alive', lambda name: False)
	browser = Browser(keep_alive=True)
	await browser.start()
	stopped_b1 = True  # the cloud browser ended; its daemon with it
	with pytest.raises(RuntimeError, match='The browser is gone'):
		await browser.reattach()
	env = await browser.start()
	assert browser.id == 'b2' and env['BU_NAME'] == browser.name and stops(cloud) == ['/browsers/b1']
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
def test_localhost_guard_spots_local_targets(task):
	from browser_use.agent.service import LOCAL_TARGET

	assert LOCAL_TARGET.search(task)  # a warning only (test_agent.py), never a refusal


@pytest.mark.parametrize('task', ['find local restaurants', 'compare 10.5 and 10.25', 'version 172.15.0.1'])
def test_localhost_guard_ignores_normal_text(task):
	from browser_use.agent.service import LOCAL_TARGET

	assert not LOCAL_TARGET.search(task)


async def test_missing_key_raises_and_never_falls_back_to_local(cloud, monkeypatch):
	monkeypatch.delenv('BROWSER_USE_API_KEY')  # and conftest points the stored-key file at nothing
	model, _ = script()
	with pytest.raises(MissingAPIKeyError, match='new-api-key'):
		await Agent('t', model).run()
	with pytest.raises(MissingAPIKeyError, match="Browser\\('chromium'\\)"):
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


async def test_a_cloud_browser_start_is_logged_at_info(cloud, caplog, monkeypatch):
	"""C21: Agent() with no browser= silently started a billed cloud browser; the only log line was DEBUG."""
	import logging

	monkeypatch.setattr(logging.getLogger('browser_use'), 'propagate', True)  # setup_logging turns it off
	caplog.set_level(logging.INFO, logger='browser_use')
	browser = Browser()
	await browser.start()
	await browser.stop()
	line = next(r for r in caplog.records if r.levelno == logging.INFO and 'b1' in r.getMessage()).getMessage()
	assert 'us proxy' in line and 'billed' in line and "Browser('chromium')" in line
	assert 'live.example.test' not in caplog.text  # the live URL grants control of the browser


async def test_the_cloud_browser_id_is_never_logged_whole_or_put_in_a_command_line(cloud, caplog, monkeypatch):
	"""The id is the cloud browser's CDP hostname and drives it without a key. Every default Browser()
	logged it at INFO and handed it to the watchdog and the MCP reaper as argv, which any local user's ps shows."""
	import logging
	import subprocess
	from types import SimpleNamespace

	from browser_use.mcp import cli_mcp

	secret_id = '0a1b2c3d-4e5f-6789-abcd-ef0123456789'
	monkeypatch.setattr(
		browser_mod,
		'_cloud',
		lambda path, method='GET', body=None: {'id': secret_id, 'cdpUrl': 'https://x.test'} if method == 'POST' else {},
	)
	spawned = []

	def popen(args, **kwargs):
		spawned.append((args, kwargs.get('env') or {}))
		return SimpleNamespace(kill=lambda: None, poll=lambda: None, stdin=None)

	monkeypatch.setattr(subprocess, 'Popen', popen)
	# Windows starts the MCP reaper through WMI instead
	monkeypatch.setattr(cli_mcp, '_spawn_outside_job', lambda args, env: spawned.append((args, env)) or True)
	monkeypatch.setattr(logging.getLogger('browser_use'), 'propagate', True)  # setup_logging turns it off
	caplog.set_level(logging.DEBUG, logger='browser_use')
	browser = Browser()
	await browser.start()
	await browser.stop()
	server = cli_mcp.CLIMCPServer()
	server._namespace = {}
	monkeypatch.setattr(cli_mcp.harness_cloud, 'start', lambda *a, **k: {'id': secret_id})
	server._start_remote()
	assert 'Browser Use cloud browser 0a1b2c3d (us proxy' in caplog.text and secret_id not in caplog.text
	assert len(spawned) == 2  # the watchdog, the reaper
	for args, env in spawned:
		assert secret_id not in ' '.join(args) and env['BU_CLEANUP_BROWSER_ID'] == secret_id


async def test_downloads_lists_a_cloud_browsers_finished_files(cloud, monkeypatch, tmp_path):
	"""Docs runs, 3 of 3 on a cloud browser: the model looked for the Browser.downloadProgress events the prompt promised,
	drained them before they arrived, found downloads/ empty (cloud files are copied at the end) and clicked again
	('sample (1).txt'). downloads() lists what the cloud API lists, without the cloud's copy of a JSON page the tab
	displayed, and the prompt points to it instead of the events."""
	import io

	from browser_use.agent.prompt import SYSTEM_PROMPT

	files = [{'path': 'report.csv', 'size': 4, 'url': 'u1'}, {'path': 'data.json', 'size': 2, 'url': 'u2'}]
	with_downloads(monkeypatch, files)
	monkeypatch.setattr(browser_mod.urllib.request, 'urlopen', lambda url, timeout=None, context=None: io.BytesIO(b'data'))
	log = tmp_path / '.browser-use' / 'downloads.jsonl'  # what the worker logs when the tab shows a JSON page
	log.parent.mkdir(parents=True)
	log.write_text('{"json_page": "https://api.test/data?q=1"}\n{"name": "data.json", "url": "https://api.test/data.json"}\n')
	model, seen = script(('python', {'code': 'print(downloads())'}), ('finish', {'success': True, 'result': 'ok'}))
	agent = Agent('t', model, browser=Browser(), workspace=tmp_path)
	result = await agent.run()
	assert result.final_result() == 'ok', result.error
	assert "[{'name': 'report.csv', 'size': 4}]" in str(seen[1][-1])
	prompt = SYSTEM_PROMPT + '\n'.join(i.instruction for i in agent._agent._instructions if isinstance(i.instruction, str))
	assert 'downloads()' in prompt and 'downloadProgress' not in prompt


def test_the_upload_advice_never_tells_the_agent_to_make_the_file(cloud):
	"""t8_files.py, 3 of 5 cloud runs: asked to upload the workspace file upload.bin, the agent first wrote
	open('upload.bin', 'wb').write(...) (the prompt said upload_file "takes local workspace paths"), uploaded 5-10 bytes
	instead of the user's 25 B / 3 MB, and reported success. The base prompt also still sent it to hand-written DataTransfer
	js, which upload_file does itself since remote uploads work."""
	from browser_use.agent.prompt import SYSTEM_PROMPT

	agent = Agent('t', script()[0], browser=Browser())
	agent._build()
	prompt = SYSTEM_PROMPT + '\n'.join(i.instruction for i in agent._agent._instructions if isinstance(i.instruction, str))
	assert 'never create or overwrite it' in prompt and 'DataTransfer' not in prompt
	assert 'takes local workspace paths' not in prompt


def test_a_download_record_the_worker_is_still_writing_counts_once_complete(tmp_path):
	"""downloads() reads the worker's downloads.jsonl mid-cell, while bu's background drain may be writing a line: a
	half-written line was skipped for good, so the cloud's copy of that JSON page would be listed and delivered."""
	log = tmp_path / 'downloads.jsonl'
	page = '{"json_page": "https://api.test/data?q=1"}\n'
	log.write_text(page + '{"name": "data.json", "url": "https://api.te')
	browser = Browser()
	browser.note_downloads(log)
	log.write_text(page + '{"name": "data.json", "url": "https://api.test/data.json"}\n')
	browser.note_downloads(log)
	assert browser.json_page_copies == {'data.json'}


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


async def test_a_download_that_keeps_failing_holds_the_stop_one_deadline_in_all(cloud, monkeypatch, tmp_path):
	"""Before the stop, up to 30 passes retried a finished download that could not be copied, each with a fresh
	DOWNLOADS_TIMEOUT_S: a blocked file host held the stop (and the billed browser) ~15 min. One deadline covers them."""
	import time

	with_downloads(monkeypatch, [{'path': '/dl/a.pdf', 'url': 'https://files.test/a'}])
	monkeypatch.setattr(browser_mod, 'DOWNLOADS_TIMEOUT_S', 1.5)

	def blocked(*a, **k):
		time.sleep(0.2)
		raise TimeoutError('timed out')

	monkeypatch.setattr(browser_mod.urllib.request, 'urlopen', blocked)
	browser = Browser()
	await browser.start()

	async def one_completed():
		return 1

	monkeypatch.setattr(browser, '_finish_downloads', one_completed)
	t = time.monotonic()
	await browser.stop(downloads_dir=tmp_path)
	assert time.monotonic() - t < 5 and stops(cloud) == ['/browsers/b1']


async def test_failed_download_is_retried_after_the_stop(cloud, monkeypatch, tmp_path):
	"""Roast r2-7: a download was marked done before it was copied; one pre-stop connection reset lost the file."""
	import io

	with_downloads(monkeypatch, [{'path': '/dl/report.pdf', 'url': 'https://files.test/r'}])
	attempts = []

	def urlopen(url, timeout=None, context=None):
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


async def test_stop_waits_for_a_running_download_and_its_cloud_listing(cloud, monkeypatch, tmp_path):
	"""C14: a 100 MB download still running when the run ended was lost: stop() never waited for it (cloud: never
	listed; local: a .crdownload), and the cloud lists a finished download about a second after it completes."""
	import io

	from browser_use.repl import worker

	monkeypatch.setattr(worker, 'STATE', tmp_path)  # the REPL worker saw a.pdf finish and b.zip start
	worker.CellStats().observe(
		[
			{'method': 'Browser.downloadWillBegin', 'params': {'guid': 'a', 'url': 'https://h/a', 'suggestedFilename': 'a.pdf'}},
			{'method': 'Browser.downloadProgress', 'params': {'guid': 'a', 'state': 'completed'}},
			{'method': 'Browser.downloadWillBegin', 'params': {'guid': 'b', 'url': 'https://h/b', 'suggestedFilename': 'b.zip'}},
		]
	)
	polls = ['inProgress', 'completed']  # what the daemon buffered for b.zip since, one drain each
	monkeypatch.setattr(
		browser_mod,
		'_daemon_request',
		lambda name, req: {
			'events': [{'method': 'Browser.downloadProgress', 'params': {'guid': 'b', 'state': polls.pop(0)}}] if polls else []
		},
	)
	real, listed_after_b = browser_mod._cloud, []

	def fake(path, method='GET', body=None):
		if 'downloads' not in path:
			return real(path, method, body)
		if browser.stopped:  # a stopped session lists nothing
			return {'files': [], 'hasMore': False}
		if not polls:
			listed_after_b.append(path)
		names = ['a.pdf', 'b.zip'] if len(listed_after_b) > 1 else ['a.pdf']  # b.zip shows up a listing late
		return {'files': [{'path': f'/dl/{n}', 'url': f'https://files.test/{n}'} for n in names], 'hasMore': False}

	monkeypatch.setattr(browser_mod, '_cloud', fake)
	monkeypatch.setattr(browser_mod.urllib.request, 'urlopen', lambda url, timeout=None, context=None: io.BytesIO(b'x'))
	browser = Browser()
	await browser.start()
	browser.note_downloads(tmp_path / 'downloads.jsonl')
	files = await browser.stop(downloads_dir=tmp_path / 'downloads')
	assert sorted(p.name for p in files) == ['a.pdf', 'b.zip'] and stops(cloud) == ['/browsers/b1']


async def test_stop_waits_for_a_download_only_the_daemon_saw_begin(cloud, monkeypatch, tmp_path):
	"""cubic: a downloadWillBegin the worker never logged (it began after the worker closed) recorded only the name: with
	its first downloadProgress in the next drain, nothing counted as running and the stop lost the download."""
	import io

	drains = [
		[{'method': 'Browser.downloadWillBegin', 'params': {'guid': 'b', 'url': 'https://h/b', 'suggestedFilename': 'b.zip'}}],
		[{'method': 'Browser.downloadProgress', 'params': {'guid': 'b', 'state': 'completed'}}],
	]
	monkeypatch.setattr(browser_mod, '_daemon_request', lambda name, req: {'events': drains.pop(0) if drains else []})
	real = browser_mod._cloud

	def fake(path, method='GET', body=None):
		if 'downloads' not in path:
			return real(path, method, body)
		done = not drains and not browser.stopped  # a stopped session lists nothing
		return {'files': [{'path': '/dl/b.zip', 'url': 'https://files.test/b'}] if done else [], 'hasMore': False}

	monkeypatch.setattr(browser_mod, '_cloud', fake)
	monkeypatch.setattr(browser_mod.urllib.request, 'urlopen', lambda url, timeout=None, context=None: io.BytesIO(b'x'))
	browser = Browser()
	await browser.start()
	files = await browser.stop(downloads_dir=tmp_path / 'downloads')
	assert [p.name for p in files] == ['b.zip'] and stops(cloud) == ['/browsers/b1']


def test_a_cdp_url_with_a_query_keeps_it_after_the_version_path(monkeypatch):
	"""cubic: 'http://host:9222/?token=t' asked http://host:9222/?token=t/json/version."""
	import io

	asked = []

	def urlopen(url, timeout=None, context=None):
		asked.append(url)
		return io.BytesIO(b'{"webSocketDebuggerUrl": "ws://host:9222/devtools/browser/x"}')

	monkeypatch.setattr(browser_mod.urllib.request, 'urlopen', urlopen)
	assert browser_mod._ws_url('http://host:9222/?token=t') == 'ws://host:9222/devtools/browser/x'
	browser_mod._ws_url('https://host/cdp/')
	browser_mod._ws_url('http://host:9222')
	assert asked == ['http://host:9222/json/version?token=t', 'https://host/cdp/json/version', 'http://host:9222/json/version']


async def test_a_download_that_sends_only_page_events_never_holds_the_stop(monkeypatch, tmp_path):
	"""RC local-1: a tab whose session never got Browser.setDownloadBehavior (Browser('chrome') on yours, a tab another
	client attached) sends only Page.download* events. Their completion was never counted, so stop() waited
	DOWNLOADS_TIMEOUT_S (300 s) and warned that the finished files were lost."""
	from browser_use.repl import worker

	def begin(guid):
		return {
			'method': 'Page.downloadWillBegin',
			'params': {'guid': guid, 'url': f'https://h/{guid}', 'suggestedFilename': guid},
		}

	def done(guid):
		return {'method': 'Page.downloadProgress', 'params': {'guid': guid, 'state': 'completed'}}

	monkeypatch.setattr(worker, 'STATE', tmp_path)
	worker.CellStats().observe([begin('a'), done('a'), begin('b')])  # b finishes after the REPL worker closed
	monkeypatch.setattr(browser_mod, '_daemon_request', lambda name, req: {'events': [done('b')]})
	monkeypatch.setattr(browser_mod, 'DOWNLOADS_TIMEOUT_S', 0)
	browser = Browser('chromium')
	browser._downloads_dir = tmp_path / 'downloads'
	browser.note_downloads(tmp_path / 'downloads.jsonl')
	assert await browser._finish_downloads() == 2


@pytest.mark.parametrize('worker_saw_begin', [True, False])
async def test_a_download_the_keep_alive_worker_saw_finish_never_holds_the_stop(monkeypatch, tmp_path, worker_saw_begin):
	"""rc5 local-download-keepalive-1: with Browser(keep_alive=True) the run leaves its REPL worker running, and it drains
	the daemon's events: it, not the stop, took the 'completed' event of a download still running as run() returned and
	logged it. The stop read the worker's log once, before it waited (and never, when the log did not exist yet), so it
	waited DOWNLOADS_TIMEOUT_S (300 s) and warned that the finished file was lost. When the stop's read took the
	download's downloadWillBegin, the worker had no name for it, so the stop names it."""
	import time

	from browser_use.browser import local as _local
	from browser_use.repl import worker

	begin = {'method': 'Browser.downloadWillBegin', 'params': {'guid': 'a', 'url': 'https://h/a', 'suggestedFilename': 'a.bin'}}
	monkeypatch.setattr(worker, 'STATE', tmp_path / '.browser-use')
	(tmp_path / '.browser-use').mkdir()
	(tmp_path / 'downloads').mkdir()
	(tmp_path / 'downloads' / 'a').write_text('x')  # Chrome saves it as its guid
	if worker_saw_begin:
		worker.CellStats().observe([begin])
	stats, drains = worker.CellStats(), []

	def drain(name, req):  # the worker takes the 'completed' event, and logs it
		drains.append(req)
		if len(drains) == 2:
			stats.observe([{'method': 'Browser.downloadProgress', 'params': {'guid': 'a', 'state': 'completed'}}])
		return {'events': [begin] if len(drains) == 1 and not worker_saw_begin else []}

	monkeypatch.setattr(browser_mod, '_daemon_request', drain)
	monkeypatch.setattr(browser_mod, 'DOWNLOADS_TIMEOUT_S', 10)
	browser = Browser('chromium')
	browser._local = _local.LocalBrowser()  # a Chrome this Browser launched: its downloads are local files
	browser._downloads_dir = tmp_path / 'downloads'
	browser.note_downloads(tmp_path / '.browser-use' / 'downloads.jsonl')  # Agent.run's, as the run ends
	started = time.monotonic()
	assert await browser._finish_downloads() == 1
	assert time.monotonic() - started < 5
	assert [p.name for p in (tmp_path / 'downloads').iterdir()] == ['a.bin']


async def test_a_cancelled_run_never_waits_for_a_running_download(cloud, monkeypatch, tmp_path):
	"""Review: task.cancel() / Ctrl-C with a download still running held the stop (and cloud billing) for
	DOWNLOADS_TIMEOUT_S, waiting for progress that would never be looked at."""
	import asyncio
	import time

	from browser_use.repl import worker

	monkeypatch.setattr(worker, 'STATE', tmp_path)
	worker.CellStats().observe(
		[{'method': 'Browser.downloadWillBegin', 'params': {'guid': 'b', 'url': 'https://h/b', 'suggestedFilename': 'b.zip'}}]
	)
	monkeypatch.setattr(browser_mod, '_daemon_request', lambda name, req: {'events': []})  # b.zip never finishes
	monkeypatch.setattr(browser_mod, 'DOWNLOADS_TIMEOUT_S', 20)
	browser = Browser()
	await browser.start()
	browser.note_downloads(tmp_path / 'downloads.jsonl')

	async def run():
		try:
			await asyncio.sleep(30)
		finally:  # as Agent.run's finally
			await browser.stop(downloads_dir=tmp_path / 'downloads')

	task = asyncio.ensure_future(run())
	await asyncio.sleep(0.05)
	t = time.monotonic()
	task.cancel()
	with pytest.raises(asyncio.CancelledError):
		await task
	assert time.monotonic() - t < 5 and stops(cloud) == ['/browsers/b1']


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
	"""Fable r3-7: Browser('chrome') (then local=True) called ensure_daemon() without a wait; browser-harness then waits forever on
	Chrome's "Allow remote debugging?" prompt, so Agent.run() hung before its timeout even started."""
	from browser_harness import admin

	calls = []

	def ensure_daemon(wait=None, name=None, env=None):  # what browser-harness does once the wait runs out
		calls.append(wait)
		if wait is None:
			raise AssertionError('unbounded wait: would hang forever on the prompt')
		raise RuntimeError("permission-blocked: Chrome's Allow popup is still open and the pending daemon was left running.")

	monkeypatch.setattr(admin, 'ensure_daemon', ensure_daemon)
	monkeypatch.setattr(admin, 'daemon_alive', lambda name=None: True)  # skip discovery of this machine's Chromes
	monkeypatch.setattr(browser_mod._local, 'require_debug_port', lambda: None)  # your Chrome has remote debugging on
	with pytest.raises(RuntimeError, match='did not allow remote debugging within 120s'):
		await Browser('chrome').start()
	assert calls == [browser_mod.LOCAL_START_WAIT_S]


async def test_cloud_create_past_its_deadline_stays_owned_and_is_stopped_when_it_lands(cloud, monkeypatch):
	"""Roast r3-4: start() waited forever on a slow POST (socket timeouts bound each read, not the response), and the
	stop's 120 s wait then gave up and disowned the browser; a create that landed later was billed, never stopped."""
	import asyncio
	import threading

	release = threading.Event()
	real = browser_mod._cloud

	def slow_cloud(path, method='GET', body=None):
		if method == 'POST':
			release.wait(10)
		return real(path, method, body)

	monkeypatch.setattr(browser_mod, '_cloud', slow_cloud)
	monkeypatch.setattr(browser_mod, 'CREATE_TIMEOUT_S', 0.3)
	browser = Browser()
	with pytest.raises(RuntimeError, match='did not create a browser within'):
		await asyncio.wait_for(browser.start(), 5)
	assert browser in browser_mod._LIVE and stops(cloud) == []  # still owned while the POST is in flight
	release.set()  # the browser lands after start() and its cleanup gave up waiting
	for _ in range(100):
		if stops(cloud):
			break
		await asyncio.sleep(0.05)
	assert stops(cloud) == ['/browsers/b1'] and not browser_mod._LIVE


@pytest.mark.skipif(sys.platform == 'win32', reason='reads the process state with ps')
async def test_stop_reaps_the_cloud_watchdog(cloud):
	"""live/scale: stop() killed a cloud browser's watchdog without waiting for it, so each one stayed a zombie until
	its Popen was garbage collected: 20 concurrent Agents left 20 zombies."""
	b = Browser()
	await b.start()
	watchdog = b._watchdog
	assert watchdog is not None
	await b.stop()
	state = subprocess.run(['ps', '-o', 'stat=', '-p', str(watchdog.pid)], capture_output=True, text=True).stdout.strip()  # noqa: ASYNC221
	assert state == ''  # gone, not a zombie (Z)


async def test_cancel_while_the_repl_closes_still_stops_the_cloud_browser(cloud, tmp_path):
	"""Roast r4-1: a cancel while Repl.close() awaited the worker's exit skipped browser.stop() (billing went on)."""
	import asyncio

	closing = asyncio.Event()

	class HangingRepl:
		async def close(self):
			closing.set()
			await asyncio.sleep(60)

	browser = Browser()
	agent = Agent('t', script()[0], browser=browser, workspace=tmp_path)
	await browser.start()
	agent._repl = HangingRepl()  # type: ignore[assignment]
	task = asyncio.ensure_future(agent.close())
	await closing.wait()
	task.cancel()
	with pytest.raises(asyncio.CancelledError):
		await task
	assert stops(cloud) == ['/browsers/b1'] and not browser_mod._LIVE


def test_windows_selector_loop_raises_before_a_cloud_browser_starts(cloud, tmp_path, monkeypatch):
	"""Fable r4-7: on a WindowsSelectorEventLoopPolicy loop the REPL subprocess raised a bare NotImplementedError, after
	a (billed) cloud browser was created. Runs on an explicit SelectorEventLoop (Windows' default is Proactor)."""
	import asyncio
	import sys

	agent = Agent('t', script()[0], browser=Browser(), workspace=tmp_path)
	loop = asyncio.SelectorEventLoop()
	monkeypatch.setattr(sys, 'platform', 'win32')
	try:
		with pytest.raises(RuntimeError, match='ProactorEventLoop'):
			loop.run_until_complete(agent.run())
	finally:
		monkeypatch.undo()
		loop.close()
	assert [c for c in cloud if c[0] == 'POST'] == []


async def test_slow_download_thread_ends_at_the_deadline(cloud, monkeypatch, tmp_path):
	"""Roast r4-4: the download deadline cancelled the await, but urlopen().read() kept the thread reading a slow-drip
	transfer; run_sync's Runner.close() and interpreter exit then joined that thread indefinitely."""
	import asyncio
	import threading
	import time
	from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

	open_conns, lock = [0], threading.Lock()

	class Drip(BaseHTTPRequestHandler):
		def do_GET(self):
			with lock:
				open_conns[0] += 1
			try:
				self.send_response(200)
				self.send_header('Content-Length', '1000000')
				self.end_headers()
				for _ in range(100):  # 20 s of one byte every 0.2 s
					self.wfile.write(b'x')
					self.wfile.flush()
					time.sleep(0.2)
			except OSError:
				pass
			finally:
				with lock:
					open_conns[0] -= 1

		def log_message(self, *a):
			pass

	server = ThreadingHTTPServer(('127.0.0.1', 0), Drip)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	try:
		with_downloads(monkeypatch, [{'path': '/dl/big.bin', 'url': f'http://127.0.0.1:{server.server_address[1]}/f'}])
		monkeypatch.setattr(browser_mod, 'DOWNLOADS_TIMEOUT_S', 1)
		browser = Browser()
		await browser.start()
		await browser.stop(downloads_dir=tmp_path)
		for _ in range(30):  # the reading threads close their connections (the server sees it on its next write)
			if open_conns[0] == 0:
				break
			await asyncio.sleep(0.1)
		assert open_conns[0] == 0
		assert list(tmp_path.iterdir()) == []  # an unfinished transfer leaves no partial file
	finally:
		server.shutdown()


async def test_downloads_never_overwrite_an_earlier_file(cloud, monkeypatch, tmp_path):
	"""Roast r4-5: two sessions (or two remote folders) with the same file name: the second write destroyed the first."""
	import io

	(tmp_path / 'report.csv').write_bytes(b'earlier session')
	with_downloads(monkeypatch, [{'path': '/a/report.csv', 'url': 'u1'}, {'path': '/b/report.csv', 'url': 'u2'}])
	monkeypatch.setattr(browser_mod.urllib.request, 'urlopen', lambda url, timeout=None, context=None: io.BytesIO(url.encode()))
	browser = Browser()
	await browser.start()
	files = await browser.stop(downloads_dir=tmp_path)
	assert (tmp_path / 'report.csv').read_bytes() == b'earlier session'
	assert [(p.name, p.read_bytes()) for p in files] == [('report (1).csv', b'u1'), ('report (2).csv', b'u2')]


def test_truncated_download_is_rejected_and_leaves_no_file(tmp_path):
	"""Roast r6-2: read1() returned EOF before Content-Length without raising, so a truncated file was accepted as
	delivered and never retried."""
	import threading
	import time
	from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

	class Short(BaseHTTPRequestHandler):
		def do_GET(self):
			self.send_response(200)
			self.send_header('Content-Length', '100')
			self.end_headers()
			self.wfile.write(b'hello')  # 5 of 100 bytes, then the connection closes

		def log_message(self, *a):
			pass

	server = ThreadingHTTPServer(('127.0.0.1', 0), Short)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	try:
		with pytest.raises(Exception, match='5 of 100|IncompleteRead|ended'):
			browser_mod._download(f'http://127.0.0.1:{server.server_port}/r.csv', tmp_path, 'r.csv', time.monotonic() + 10)
	finally:
		server.shutdown()
	assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
	'kwargs, option',
	[
		({'kind': 'chromium', 'cloud_proxy_country_code': 'de'}, 'cloud_proxy_country_code'),
		({'kind': 'chromium', 'cloud_proxy_country_code': 'us'}, 'cloud_proxy_country_code'),  # = the default
		({'kind': 'chrome', 'cloud_proxy_country_code': None}, 'cloud_proxy_country_code'),
		({'cdp_url': 'http://x:9222', 'cloud_proxy_country_code': 'de'}, 'cloud_proxy_country_code'),
		({'local': True, 'cloud_timeout': 5}, 'cloud_timeout'),
		({'cdp_url': 'http://x:9222', 'cloud_timeout': 60}, 'cloud_timeout'),
	],
)
def test_cloud_options_on_a_local_or_cdp_browser_raise(kwargs, option):
	"""browser-features #4: Browser('chromium', cloud_proxy_country_code='de') ran with no proxy, silently."""
	with pytest.raises(ValueError, match=f'does not take {option}='):
		Browser(**kwargs)
	assert Browser(cloud_proxy_country_code='us', cloud_timeout=60).proxy == 'us'  # explicit on cloud is fine


@pytest.mark.parametrize(
	'kwargs, match',
	[
		({'cloud_proxy_country_code': 'usa'}, 'two-letter country code'),
		({'cloud_proxy_country_code': 1}, 'two-letter country code'),
		({'cloud_proxy_country_code': ''}, 'two-letter country code'),
		({'cloud_timeout': 0}, 'from 1 to 240'),
		({'cloud_timeout': True}, 'from 1 to 240'),
		({'cloud_timeout': 241}, 'from 1 to 240'),
		({'cloud_timeout': 5.5}, 'from 1 to 240'),
		({'captcha_solver': 'no'}, 'True or False'),
	],
)
def test_bad_cloud_options_raise_before_any_request(kwargs, match):
	"""M20 (and lows): a bad proxy country came back from the API as a 500-character validation dump, an int raised
	AttributeError, cloud_timeout=0 meant 60 and True meant 1 minute, captcha_solver='no' counted as on."""
	with pytest.raises((ValueError, TypeError), match=match):
		Browser(**kwargs)
	assert Browser(cloud_proxy_country_code='DE', cloud_timeout=240).proxy == 'de'


def test_proxy_country_code_is_sent_lowercase():
	"""browser-features #26: 'DE' got the API's raw 422 enum dump; the API takes only lowercase codes."""
	assert Browser(cloud_proxy_country_code='DE').proxy == 'de'
	assert Browser().proxy == 'us' and Browser(cloud_proxy_country_code=None).proxy is None


def test_uppercase_profile_uuid_is_an_id_not_a_name(cloud):
	"""browser-features #9: an uppercase UUID was looked up as a profile name ('0 cloud profiles are named ...')."""
	assert browser_mod._profile_id('0A1B2C3D-4E5F-6789-ABCD-EF0123456789') == '0a1b2c3d-4e5f-6789-abcd-ef0123456789'
	assert not [c for c in cloud if 'profiles' in c[1]]


async def test_live_and_cdp_urls_are_cleared_after_stop(cloud):
	"""browser-features #12: both stayed on the object after stop(), where a repr or log could carry them."""
	browser = Browser()
	await browser.start()
	assert browser.live_url and browser.cloud_cdp_url
	await browser.stop()
	assert (browser.live_url, browser.cloud_cdp_url) == (None, None)


async def test_download_with_a_name_too_long_for_the_filesystem_is_shortened(cloud, monkeypatch, tmp_path):
	"""browser-features #8: a name of 255 bytes plus ' (1)' raised 'File name too long' on every retry: the file was
	never copied."""
	import io

	long = 'é' * 126 + 'x.csv'  # 257 bytes
	(tmp_path / 'existing').mkdir()
	with_downloads(monkeypatch, [{'path': long, 'url': 'u1'}, {'path': f'b/{long}', 'url': 'u2'}])
	monkeypatch.setattr(browser_mod.urllib.request, 'urlopen', lambda url, timeout=None, context=None: io.BytesIO(url.encode()))
	browser = Browser()
	await browser.start()
	files = await browser.stop(downloads_dir=tmp_path / 'existing')
	assert [p.read_bytes() for p in files] == [b'u1', b'u2']
	assert all(len(p.name.encode()) <= 255 and p.suffix == '.csv' for p in files), [p.name for p in files]
	assert files[1].name.endswith(' (1).csv')


async def test_a_json_page_the_cloud_browser_saved_is_not_copied(cloud, monkeypatch, tmp_path):
	"""browser-features #6: a cloud browser saves a JSON page it displays as a download (https://httpbin.org/cookies
	-> cookies.json, cookie values included); the agent's workspace got a copy."""
	import io
	import json

	log = tmp_path / 'downloads.jsonl'
	log.write_text(
		'\n'.join(
			json.dumps(r)
			for r in [
				{'name': 'cookies.json', 'url': 'https://httpbin.org/cookies.json'},
				{'json_page': 'https://httpbin.org/cookies'},
				{'name': 'cookies.json', 'url': 'https://httpbin.org/cookies.json'},  # shown again: listed as cookies (1).json
				{'name': 'get.json', 'url': 'https://httpbin.org/get.json'},  # seen on cloud: the query is dropped
				{'json_page': 'https://httpbin.org/get?a=1'},
				{'name': 'r.csv', 'url': 'https://httpbin.org/response-headers?x=1'},
				{'name': 'data.json', 'url': 'https://files.example/data.json'},  # a real JSON download
				{'json_page': 'https://httpbin.org/json'},
				{'name': 'json.json', 'url': 'https://httpbin.org/json.json'},
				{'name': 'json.json', 'url': 'https://httpbin.org/response-headers?filename=json.json'},  # real (M19)
			]
		)
	)
	listed = ('cookies.json', 'cookies (1).json', 'get.json', 'r.csv', 'data.json', 'json.json', 'json (1).json')
	files = [{'path': p, 'url': p} for p in listed]
	with_downloads(monkeypatch, files)
	monkeypatch.setattr(browser_mod.urllib.request, 'urlopen', lambda url, timeout=None, context=None: io.BytesIO(url.encode()))
	browser = Browser()
	browser.json_page_copies |= browser_mod.json_page_copies(log)
	await browser.start()
	copied = await browser.stop(downloads_dir=tmp_path / 'dl')
	assert sorted(p.name for p in copied) == ['data.json', 'json (1).json', 'r.csv']


def test_json_copies_of_every_json_type_are_found_and_a_real_file_sharing_the_name_is_kept(tmp_path):
	"""M18: only application/json pages counted, so +json and text/json copies were delivered as downloads. M19: the
	filter matched by name with ' (n)' stripped, so a real download named like a copy ('json (1).json') was dropped."""
	import json

	from browser_use.repl import worker

	stats, real = worker.CellStats(), 'https://httpbin.org/response-headers?Content-Type=application%2Fjson&x=1'
	worker.STATE, saved = tmp_path, worker.STATE
	try:
		stats.observe(
			[
				{'method': 'Page.frameNavigated', 'params': {'frame': {'url': f'https://h/{n}?a=1', 'mimeType': m}}}
				for n, m in (('api', 'application/vnd.api+json'), ('t', 'text/json'), ('p', 'application/problem+json'))
			]
		)
	finally:
		worker.STATE = saved
	log = tmp_path / 'downloads.jsonl'
	with open(log, 'a') as f:
		for r in [
			{'name': 'api', 'url': 'https://h/api'},
			{'name': 't (1)', 'url': 'https://h/t%20(1)'},
			{'name': 'p', 'url': 'https://h/p'},
			{'json_page': 'https://httpbin.org/json'},
			{'name': 'json.json', 'url': 'https://httpbin.org/json.json'},
			{'name': 'json.json', 'url': real},  # a real download with the copy's name: listed as json (1).json
		]:
			f.write(json.dumps(r) + '\n')
	assert browser_mod.json_page_copies(log) == {'api', 't (1)', 'p', 'json.json'}


@pytest.mark.parametrize('order', ['page first', 'download first'])
def test_a_json_page_the_cloud_browser_saved_is_not_announced_as_a_download(tmp_path, order):
	"""Live: opening https://ipinfo.io/json on a cloud browser printed '[download started: json.json]' to the model,
	which never downloaded anything (downloads() and result.downloads leave the copy out). A real download still is."""
	from browser_use.repl import worker

	page = {
		'method': 'Page.frameNavigated',
		'params': {'frame': {'url': 'https://ipinfo.io/json', 'mimeType': 'application/json'}},
	}
	copy = {
		'method': 'Browser.downloadWillBegin',
		'params': {'guid': 'g1', 'url': 'https://ipinfo.io/json.json', 'suggestedFilename': 'json.json'},
	}
	real = {
		'method': 'Browser.downloadWillBegin',
		'params': {'guid': 'g2', 'url': 'https://h/r.csv', 'suggestedFilename': 'r.csv'},
	}
	stats = worker.CellStats()
	worker.STATE, saved = tmp_path, worker.STATE
	try:
		stats.observe([page, copy, real] if order == 'page first' else [copy, page, real])
	finally:
		worker.STATE = saved
	assert stats.started == ['r.csv']
	assert '"json.json"' in (tmp_path / 'downloads.jsonl').read_text()  # still logged: Browser.json_page_copies reads it


def test_json_copies_are_numbered_across_every_agent_on_one_cloud_browser(cloud, tmp_path):
	"""Review: each workspace's log was numbered on its own, but the cloud numbers a repeated name across the whole
	session: the second Agent's cookies copy, listed as 'cookies (1).json' (cookies the page echoed), was delivered."""
	import asyncio
	import json

	def log(name: str, *records: dict):
		path = tmp_path / name / 'downloads.jsonl'
		path.parent.mkdir(exist_ok=True)
		with open(path, 'a') as f:
			f.writelines(json.dumps(r) + '\n' for r in records)
		return path

	page, copy = {'json_page': 'https://httpbin.org/cookies'}, {'name': 'cookies.json', 'url': 'https://httpbin.org/cookies.json'}
	browser = Browser(keep_alive=True)
	asyncio.run(browser.start())
	a = log('a', page, copy)
	browser.note_downloads(a)
	browser.note_downloads(log('b', page, copy, {'name': 'data.json', 'url': 'https://files.example/data.json'}))
	assert browser.json_page_copies == {'cookies.json', 'cookies (1).json'}
	browser.note_downloads(log('a', copy))  # a follow-up run of the first Agent: only its new line counts
	assert browser.json_page_copies == {'cookies.json', 'cookies (1).json', 'cookies (2).json'}
	asyncio.run(browser.stop())
	assert browser.json_page_copies == set()  # the next cloud session numbers its downloads anew


def test_worker_logs_downloads_and_json_pages_for_the_parent(tmp_path, monkeypatch):
	from browser_use.repl import worker

	monkeypatch.setattr(worker, 'STATE', tmp_path)
	s = worker.CellStats()
	s.observe(
		[
			{
				'method': 'Browser.downloadWillBegin',
				'params': {'guid': 'g', 'url': 'https://h/j.json', 'suggestedFilename': 'j.json'},
			},
			{
				'method': 'Page.downloadWillBegin',
				'params': {'guid': 'g', 'url': 'https://h/j.json', 'suggestedFilename': 'j.json'},
			},
			{'method': 'Page.frameNavigated', 'params': {'frame': {'url': 'https://h/j', 'mimeType': 'application/json'}}},
			{'method': 'Page.frameNavigated', 'params': {'frame': {'url': 'https://h/x', 'mimeType': 'text/html'}}},
		]
	)
	assert browser_mod.json_page_copies(tmp_path / 'downloads.jsonl') == {'j.json'}


async def test_cloud_daemon_knows_its_browser_id(cloud, monkeypatch):
	"""browser-features #3 / lifecycle F3: with only BU_CDP_WS the daemon opened a hidden background tab (every first
	cloud screenshot waited 10 s) and could not stop the cloud browser itself."""
	from browser_harness import admin

	envs = []
	monkeypatch.setattr(admin, 'ensure_daemon', lambda *a, **k: envs.append(k['env']))
	browser = Browser()
	await browser.start()
	await browser.stop()
	assert envs[0]['BU_BROWSER_ID'] == 'b1' and envs[0]['BU_CDP_WS']
	envs.clear()
	local = Browser(cdp_url='http://127.0.0.1:9')
	monkeypatch.setattr(browser_mod, '_ws_url', lambda url: 'ws://127.0.0.1:9/devtools/browser/x')
	await local.start()
	await local.stop()
	assert 'BU_BROWSER_ID' not in envs[0]


async def test_a_daemon_that_acknowledged_shutdown_already_stopped_the_cloud_browser(cloud, monkeypatch):
	monkeypatch.setattr(browser_mod, '_shutdown_daemon', lambda name: True)
	browser = Browser()
	await browser.start()
	await browser.stop()
	assert browser.stopped and stops(cloud) == [] and not browser_mod._LIVE


def test_signal_handlers_are_installed_on_the_main_thread_after_a_start_on_another(monkeypatch):
	"""Lifecycle F1: _install_cleanup() off the main thread marked the handlers installed without installing them, so a
	SIGTERM never stopped the cloud browser. F4: SIGHUP (terminal closed) was not handled at all."""
	import signal
	import threading

	monkeypatch.setattr(browser_mod, '_signals_installed', False)
	monkeypatch.setattr(browser_mod, '_atexit_installed', True)
	monkeypatch.setattr(signal, 'getsignal', lambda s: signal.SIG_DFL)
	installed = {}
	monkeypatch.setattr(signal, 'signal', lambda s, h: installed.__setitem__(s, h))
	t = threading.Thread(target=browser_mod._install_cleanup)
	t.start()
	t.join()
	assert installed == {}
	Browser()  # the next main-thread entry
	expected = [signal.SIGTERM] + ([signal.SIGHUP] if hasattr(signal, 'SIGHUP') else [])  # no SIGHUP on Windows
	assert installed == dict.fromkeys(expected, browser_mod._on_signal)


SIGHUP_CHILD = """
import asyncio, os, signal, sys
from browser_use.browser import browser as b
stopped = []
class Fake:
	def _stop_now(self):
		stopped.append(1)
		sys.stdout.write('stopped\\n'); sys.stdout.flush()
b._LIVE.add(Fake())
b._install_cleanup()
os.kill(os.getpid(), signal.SIGHUP)
"""


@pytest.mark.skipif(not hasattr(__import__('signal'), 'SIGHUP'), reason='no SIGHUP on Windows')
def test_sighup_stops_live_browsers_then_exits():
	import subprocess
	import sys

	r = subprocess.run([sys.executable, '-c', SIGHUP_CHILD], capture_output=True, text=True, timeout=60)
	assert r.stdout.strip() == 'stopped' and r.returncode == -1, (r.returncode, r.stdout, r.stderr[-2000:])


def test_headers_raise_until_the_daemon_sends_them():
	"""C18 accepted headers= but the pinned browser-harness daemon never sent them on the WebSocket handshake: an
	authenticated cdp_url passed /json/version, then failed inside ensure_daemon with a bare 401/403."""
	with pytest.raises(TypeError, match='WebSocket handshake'):
		Browser(cdp_url='https://example.invalid', headers={'Authorization': 'AWS4-HMAC-SHA256 x'})


@pytest.mark.parametrize('url', ['http://127.0.0.1:{port}', 'ws://127.0.0.1:{port}/devtools/browser/x?token=s3cret'])
async def test_a_cdp_url_nothing_answers_on_names_the_cdp_url(url, tmp_path):
	"""Live: Browser(cdp_url=...) with no browser there failed with a bare '<urlopen error [Errno 61] Connection
	refused>' (http), or browser-harness's 'If you use Browser Use cloud, verify auth and get a fresh URL via
	start_remote_daemon()' (ws), which is not what a cdp_url user runs. The error names the cdp_url and its fix; a
	token in the URL is never echoed."""
	import socket

	with socket.socket() as s:
		s.bind(('127.0.0.1', 0))
		port = s.getsockname()[1]
	model, _ = script()
	result = await Agent('t', model, browser=Browser(cdp_url=url.format(port=port)), workspace=tmp_path).run()
	assert result.status == 'error', result
	assert 'cdp_url' in (result.error or '') and f'127.0.0.1:{port}' in result.error, result.error
	assert 'start_remote_daemon' not in result.error and 's3cret' not in result.error, result.error
