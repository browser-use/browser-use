"""The missing-key path: library_auth telemetry (enums only, never key material, nothing when off), the improved
MissingAPIKeyError, the device-code login a run starts by itself over SSH, and Ctrl-C ending that login. No test reaches
Browser Use Cloud: logins and cloud calls are mocked."""

import asyncio
import io
import json
import os
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest
from conftest import script

from browser_use import Agent, Browser, ChatBrowserUse
from browser_use.exceptions import MissingAPIKeyError

KEY = 'bu_' + 'k' * 40  # shaped like a real key: a leak would show in any event
SSH = '10.0.0.1 5000 10.0.0.2 22'


@pytest.fixture
def events(monkeypatch, tmp_path):
	"""Every event telemetry would send (agent_event, library_auth, ...), built as the thread builds them; a config dir of
	this test's own; no key in the env or the store; a fresh automatic-login attempt."""
	import browser_use.auth as auth
	import browser_use.telemetry.service as service
	from browser_use.telemetry import auth_events

	sent: list[dict] = []

	class FakeTelemetry:
		enabled = True
		notice = True

		def run_started(self, run_id, props, progress):
			pass

		def capture_run(self, job):
			sent.append({'event': job.name, **job.build(200, 50)})

		def capture(self, event):
			sent.append({'event': event.name, **event.properties})

	monkeypatch.setattr(service, 'telemetry', FakeTelemetry)
	monkeypatch.setattr(auth, '_login_attempted', False)
	monkeypatch.setattr(auth, '_reported_key_sources', set())
	monkeypatch.setattr(auth_events, '_entry', ['agent'])  # an in-process cli.main() of another test named it cli
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path / 'config'))
	monkeypatch.setenv('BH_AUTH_PATH', str(tmp_path / 'bh' / 'auth.json'))
	monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)
	return sent


def auth_events_of(sent: list[dict]) -> list[dict]:
	return [e for e in sent if e['event'] == 'library_auth']


def stages(sent: list[dict]) -> list[str]:
	return [e['stage'] for e in auth_events_of(sent)]


def no_key_material(sent: list[dict]) -> None:
	blob = json.dumps(sent, default=str)
	for value in (KEY, KEY[:12], 'api_key_id', 'project_id', 'auth_url', 'state=', 'code=', 'WXYZ-1234'):
		assert value not in blob, value


class Terminal(io.StringIO):
	def isatty(self) -> bool:
		return True


def over_ssh(monkeypatch) -> Terminal:
	"""stdin and stderr are terminals of an SSH session, not CI or a container, automatic login not turned off."""
	import browser_use.config as config

	stderr = Terminal()
	monkeypatch.setattr('sys.stdin', Terminal())
	monkeypatch.setattr('sys.stderr', stderr)
	monkeypatch.setattr(config, 'is_in_container', lambda: False)
	for name in ('CI', 'GITHUB_ACTIONS', 'BROWSER_USE_AUTO_LOGIN'):
		monkeypatch.delenv(name, raising=False)
	monkeypatch.setenv('SSH_CONNECTION', SSH)
	return stderr


def device_code_approves(monkeypatch, starts: list[str]) -> None:
	"""browser-harness's device login, approved at once: KEY stored as the harness stores it (source oauth)."""
	from browser_harness import auth

	def start(open_url=True):
		starts.append('device')
		return SimpleNamespace(open_uri='https://cloud.browser-use.test/device?code=WXYZ-1234', user_code='WXYZ-1234')

	def complete(start, timeout=None):
		auth.save_auth_record(auth.AuthRecord(api_key=KEY, source='oauth'))

	monkeypatch.setattr(auth, 'start_device_auth', start)
	monkeypatch.setattr(auth, 'complete_device_auth', complete)
	monkeypatch.setattr(auth, 'start_browser_auth', lambda **kwargs: pytest.fail('a browser login over SSH'))


def local_browser(monkeypatch) -> Browser:
	async def start(self):
		return {}

	async def stop(self, downloads_dir=None):
		return []

	monkeypatch.setattr(Browser, 'start', start)
	monkeypatch.setattr(Browser, 'stop', stop)
	return Browser('chromium')


async def test_the_default_model_without_a_key_is_counted_with_its_gate(events, tmp_path):
	"""Agent(task) with no key raised in _build, before the run's telemetry started: the README path sent no run."""
	with pytest.raises(MissingAPIKeyError) as raised:
		await Agent('Zq9 task', browser=Browser('chromium'), workspace=tmp_path).run()
	assert (raised.value.key_gate, raised.value.key_reason) == ('default_model', 'missing')
	(run,) = (e for e in events if e['event'] == 'agent_event')
	assert (run['status'], run['error_type'], run['error_phase']) == ('error', 'MissingAPIKeyError', 'build')
	assert (run['key_gate'], run['key_reason'], run['key_source'], run['model'], run['gateway']) == (
		'default_model',
		'missing',
		'none',
		'bu-4.0',
		True,
	)
	assert run['error_messages'] and 'Zq9' not in json.dumps(events)
	(gate,) = auth_events_of(events)
	assert (gate['stage'], gate['key_gate'], gate['key_reason'], gate['entry'], gate['automatic']) == (
		'missing_key',
		'default_model',
		'missing',
		'agent',
		True,
	)
	assert (gate['gate_count'], gate['seconds_since_first_gate'], gate['method'], gate['schema_version']) == (1, 0, '', 6)
	assert {'is_ssh', 'is_colab', 'has_display', 'is_notebook', 'is_ci', 'is_internal'} <= set(gate)
	with pytest.raises(MissingAPIKeyError):  # the device's second gate: counted locally, the first time kept
		await Agent('t', browser=Browser('chromium'), workspace=tmp_path).run()
	assert [e['gate_count'] for e in auth_events_of(events)] == [1, 2]
	no_key_material(events)


async def test_an_own_model_on_the_default_cloud_browser_sends_its_gate_on_the_agent_event(events, tmp_path):
	with pytest.raises(MissingAPIKeyError):
		await Agent('t', script()[0], workspace=tmp_path).run()
	(run,) = (e for e in events if e['event'] == 'agent_event')
	assert (run['error_phase'], run['key_gate'], run['key_reason']) == ('browser_start', 'cloud_browser', 'missing')
	assert run['error_messages'] == [
		'Browser() (a Browser Use Cloud browser) needs a Browser Use API key. Sign in once: `browser-use login` (over SSH '
		'or in a container: `browser-use login --device-code`).'
	]
	assert [(e['stage'], e['key_gate']) for e in auth_events_of(events)] == [('missing_key', 'cloud_browser')]


async def test_telemetry_off_sends_nothing_and_writes_no_file_on_a_gate(tmp_path, monkeypatch):
	import urllib.request

	import browser_use.telemetry.service as service
	from browser_use.auth import record_auth_event
	from browser_use.telemetry.auth_events import keyed_success

	config = tmp_path / 'config'
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'false')
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(config))
	monkeypatch.setenv('BH_AUTH_PATH', str(tmp_path / 'bh' / 'auth.json'))
	monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)
	monkeypatch.setattr(service, '_device_id', None)
	instance = service.ProductTelemetry()
	monkeypatch.setattr(service, '_instance', instance)

	def forbidden(*args, **kwargs):
		raise AssertionError(f'called with telemetry off: {args[:1]}')

	monkeypatch.setattr(urllib.request, 'urlopen', forbidden)
	monkeypatch.setattr(subprocess, 'Popen', forbidden)
	for agent in (Agent('t', browser=Browser('chromium'), workspace=tmp_path), Agent('t', script()[0], workspace=tmp_path)):
		with pytest.raises(MissingAPIKeyError):
			await agent.run()
	record_auth_event('login_started', method='device', automatic=True)
	keyed_success()
	instance._at_exit()
	assert instance._thread is None and not instance._pending
	assert not [p for p in config.rglob('*') if p.is_file()]


async def test_a_script_without_a_terminal_never_starts_a_login(events, tmp_path, monkeypatch):
	from browser_use import cli

	over_ssh(monkeypatch)
	monkeypatch.setattr('sys.stdin', io.StringIO())  # piped
	monkeypatch.setattr(cli, '_run_login_command', lambda *a, **k: pytest.fail('a login without a terminal'))
	with pytest.raises(MissingAPIKeyError):
		await Agent('t', browser=Browser('chromium'), workspace=tmp_path).run()
	assert stages(events) == ['missing_key']


async def test_over_ssh_a_run_signs_in_with_a_device_code_and_goes_on(events, tmp_path, monkeypatch):
	"""The desktop login opened a browser nobody at an SSH terminal sees (and its loopback callback is out of their
	browser's reach), or none on Linux without a desktop: the run ended at the missing-key error. Now it prints a link and
	a code, stores the key once approved, and the same run finishes; the device's first keyed run is reported once."""
	from browser_use.search import WebSearch

	stderr = over_ssh(monkeypatch)
	starts: list[str] = []
	device_code_approves(monkeypatch, starts)
	monkeypatch.setattr(WebSearch, 'preflight', lambda self: None)
	model, _ = script(('finish', {'success': True, 'result': 'ok'}))
	agent = Agent('t', model, browser=local_browser(monkeypatch), workspace=tmp_path, web_search=True)
	result = await agent.run()
	assert result.status == 'completed' and starts == ['device']
	assert agent._search is not None and agent._search.api_key == KEY
	lines = stderr.getvalue().splitlines()
	assert lines[:2] == [
		'Browser Use needs a key. No browser opens here (SSH or no desktop): approve the code below on any device to '
		'continue this run.',
		'Approve Browser Use access on any device: https://cloud.browser-use.test/device?code=WXYZ-1234 (code WXYZ-1234)',
	]
	assert stages(events) == ['missing_key', 'login_started', 'login_succeeded', 'key_available', 'keyed_success']
	gate, started, stored, _, keyed = auth_events_of(events)
	assert (gate['key_gate'], started['method'], started['automatic'], stored['outcome']) == (
		'web_search',
		'device',
		True,
		'stored',
	)
	assert (keyed['gate_count'], keyed['seconds_since_first_gate'] is not None) == (1, True)
	(run,) = (e for e in events if e['event'] == 'agent_event')
	assert (run['status'], run['key_source'], run['key_gate']) == ('completed', 'login_device', None)
	no_key_material(events)

	await Agent(
		't', script(('finish', {'success': True, 'result': 'ok'}))[0], browser=local_browser(monkeypatch), workspace=tmp_path
	).run()
	assert stages(events).count('keyed_success') == 1  # once per device


def test_which_login_a_missing_key_starts(monkeypatch):
	import browser_use.auth as auth
	import browser_use.config as config

	over_ssh(monkeypatch)
	monkeypatch.setattr(auth, '_can_open_login', lambda: True)  # a Mac reached over SSH: its screen is not the user's
	assert auth.auto_login_method() == 'device'
	monkeypatch.delenv('SSH_CONNECTION')
	assert auth.auto_login_method() == 'browser'
	monkeypatch.setattr(auth, '_can_open_login', lambda: False)
	monkeypatch.setattr(auth.sys, 'platform', 'linux')  # a Linux terminal without a desktop
	assert auth.auto_login_method() == 'device'
	monkeypatch.setattr(config, 'is_in_container', lambda: True)  # `docker run -t`: nobody may read the code
	assert auth.auto_login_method() is None
	monkeypatch.setenv('BROWSER_USE_AUTO_LOGIN', '1')
	assert auth.auto_login_method() == 'device'
	for name, value in (('BROWSER_USE_AUTO_LOGIN', 'false'), ('CI', '1')):
		with monkeypatch.context() as patch:
			patch.setenv(name, value)
			assert auth.auto_login_method() is None
	monkeypatch.setattr('sys.stderr', io.StringIO())  # the code would go to a file nobody reads
	assert auth.auto_login_method() is None
	monkeypatch.setattr('sys.stderr', Terminal())
	monkeypatch.setattr(auth.sys, 'platform', 'darwin')  # a desktop that refused (no terminal, ...): no device code
	assert auth.auto_login_method() is None


def test_podman_and_kubernetes_count_as_containers(monkeypatch):
	"""Only Docker was detected: a pod with tty: true or `podman run -t` waited on a device code until it expired."""
	import browser_use.config as config

	monkeypatch.setattr(config, 'is_running_in_docker', lambda: False)
	monkeypatch.delenv('container', raising=False)
	monkeypatch.setenv('KUBERNETES_SERVICE_HOST', '10.96.0.1')
	assert config.is_in_container()
	monkeypatch.delenv('KUBERNETES_SERVICE_HOST')
	monkeypatch.setenv('container', 'podman')
	assert config.is_in_container()


async def test_a_missing_key_never_signs_in_where_the_wait_would_block_others(events, monkeypatch):
	"""The login blocks its thread until approved (a device code: until it expires). Beside other tasks on the loop
	(asyncio.gather, a server) every one of them stalled for the whole wait; on a worker thread (a ThreadPoolExecutor,
	Streamlit) Ctrl-C never reached it. Both fail fast with the missing-key error now."""
	import browser_use.auth as auth
	from browser_use import cli

	over_ssh(monkeypatch)
	monkeypatch.setattr(cli, '_run_login_command', lambda *a, **k: pytest.fail('a login that blocks others'))
	other = asyncio.create_task(asyncio.sleep(30))
	try:
		with pytest.raises(MissingAPIKeyError):
			auth.browser_use_api_key(gate='cloud_browser', auto_login=True)
	finally:
		other.cancel()
	with pytest.raises(MissingAPIKeyError):
		await asyncio.to_thread(auth.browser_use_api_key, gate='cloud_browser', auto_login=True)
	await asyncio.sleep(0)  # the cancelled task ends
	assert auth.auto_login_method() == 'device'  # the loop's one task, on the main thread: it signs in


def test_a_login_that_breaks_off_ends_with_the_missing_key_error(events, monkeypatch):
	"""A token poll whose read timed out (TimeoutError, not wrapped by browser-harness) or a reply that is not JSON
	escaped raw: Agent.run raised it instead of MissingAPIKeyError, and the run's gate was never sent."""
	from browser_harness import auth as harness

	import browser_use.auth as auth

	over_ssh(monkeypatch)
	device_code_approves(monkeypatch, [])

	def times_out(start, timeout=None):
		raise TimeoutError('The read operation timed out')

	monkeypatch.setattr(harness, 'complete_device_auth', times_out)
	with pytest.raises(MissingAPIKeyError) as raised:
		auth.browser_use_api_key(gate='default_model', auto_login=True)
	assert isinstance(raised.value.__cause__, TimeoutError) and raised.value.key_gate == 'default_model'
	assert [(e['stage'], e.get('outcome')) for e in auth_events_of(events)] == [
		('missing_key', None),
		('login_started', None),
		('login_failed', 'network'),
	]


async def test_a_key_store_error_sends_no_path(events, tmp_path, monkeypatch):
	"""Its first line names the store; scrub keeps paths outside HOME (BH_AUTH_PATH=/srv/<customer>/auth.json)."""
	store = tmp_path / 'acme-payroll' / 'auth.json'
	store.parent.mkdir()
	store.write_text('{not json')
	monkeypatch.setenv('BH_AUTH_PATH', str(store))
	for agent in (Agent('t', browser=Browser('chromium'), workspace=tmp_path), Agent('t', script()[0], workspace=tmp_path)):
		with pytest.raises(MissingAPIKeyError, match='acme-payroll'):  # the user still reads it
			await agent.run()
	runs = [e for e in events if e['event'] == 'agent_event']
	assert [r['error_messages'] for r in runs] == [
		['The default model (bu-4.0) needs a Browser Use API key (corrupt_store)'],
		['Browser() (a Browser Use Cloud browser) needs a Browser Use API key (corrupt_store)'],
	]
	assert 'acme-payroll' not in json.dumps(events)


def test_links_are_untagged_with_telemetry_off():
	"""The keys and billing links carried ref, gate and the version to cloud.browser-use.com with telemetry off."""
	from browser_use.exceptions import KEYS_URL
	from browser_use.llm import BILLING_URL

	text = str(MissingAPIKeyError('The default model (bu-fast)', gate='default_model'))  # conftest: telemetry off
	assert f'{KEYS_URL}\n' in text and 'ref=' not in text
	unpaid = ChatBrowserUse(api_key='bu_test')._explain(402, 'payment_required', None)
	assert unpaid and f'{BILLING_URL}\n' in unpaid and 'ref=' not in unpaid


@pytest.mark.skipif(os.name != 'posix', reason='SIGINT to a child process')
def test_ctrl_c_ends_the_automatic_login_of_run_sync_with_the_missing_key_error(tmp_path):
	"""asyncio.Runner (run_sync, asyncio.run) turns the first Ctrl-C into a cancel of the run's task, which the login's
	blocking wait never sees: Ctrl-C did nothing until the login's 600 s timeout."""
	import signal
	import time

	code = f"""
import sys, time
from types import SimpleNamespace
from browser_harness import auth as harness
import browser_use.auth as auth
from browser_use import Agent, Browser
from browser_use.exceptions import MissingAPIKeyError

auth._can_open_login = lambda: True
harness.start_browser_auth = lambda **kw: SimpleNamespace(auth_url='http://127.0.0.1:9/approve')
harness.complete_browser_auth = lambda start, **kw: time.sleep(30)
try:
	Agent('t', browser=Browser('chromium'), workspace={str(tmp_path)!r}).run_sync()
except MissingAPIKeyError as e:
	print('RAISED', e.key_gate, flush=True)
"""
	env = {**os.environ, 'ANONYMIZED_TELEMETRY': 'false', 'BH_AUTH_PATH': str(tmp_path / 'auth.json')}
	env.pop('BROWSER_USE_API_KEY', None)
	child = subprocess.Popen(
		[sys.executable, '-c', code], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=tmp_path
	)
	try:
		assert child.stderr is not None
		for line in child.stderr:
			if line.startswith('Approve Browser Use access'):
				break
		time.sleep(0.3)
		child.send_signal(signal.SIGINT)
		out, err = child.communicate(timeout=15)
	finally:
		child.kill()
	assert out.strip() == 'RAISED default_model' and 'Login cancelled.' in err and 'Traceback' not in err


def test_cli_login_over_ssh_uses_a_device_code_and_records_its_outcome(events, monkeypatch, capsys):
	from browser_harness import auth

	from browser_use import cli

	monkeypatch.setenv('SSH_CONNECTION', SSH)
	for var in ('BH_CLIENT', 'BH_CLIENT_VERSION', 'BH_DEVICE_NAME'):
		monkeypatch.delenv(var, raising=False)
	calls: list[str] = []

	def device_login(**kwargs):
		calls.append('device')
		raise auth.AuthError('timed out waiting for device auth')

	monkeypatch.setattr(auth, 'device_login', device_login)
	monkeypatch.setattr(auth, 'browser_login', lambda **kwargs: calls.append('browser'))
	assert cli._run_login_command([]) == 1 and calls == ['device']
	assert 'signing in with a device code' in capsys.readouterr().err
	assert [(e['stage'], e['method'], e['outcome'], e['automatic']) for e in auth_events_of(events)] == [
		('login_started', 'device', None, False),
		('login_failed', 'device', 'device_timeout', False),
	]

	def callback_timeout(**kwargs):
		raise auth.AuthError('timed out waiting for browser auth callback')

	monkeypatch.delenv('SSH_CONNECTION')
	monkeypatch.setattr(auth, 'browser_login', callback_timeout)
	assert cli._run_login_command(['--no-open']) == 1  # --no-open: the link, for a browser the user opens
	assert '`browser-use login --device-code`' in capsys.readouterr().err  # the loopback timeout names the way out
	assert (events[-1]['outcome'], events[-1]['method']) == ('callback_timeout', 'browser')
	no_key_material(events)


def test_a_device_login_leaves_the_key_file_alone_with_telemetry_off(events, monkeypatch):
	"""Marking a device-code login's source is for telemetry only: off, it is no second write to the key file."""
	from browser_harness import auth as harness

	import browser_use.telemetry.service as service
	from browser_use.auth import mark_device_login

	harness.save_auth_record(harness.AuthRecord(api_key=KEY, source='oauth'))
	monkeypatch.setattr(service.telemetry, 'enabled', False)
	monkeypatch.setattr(harness, 'save_auth_record', lambda record: pytest.fail('rewrote the key file with telemetry off'))
	mark_device_login()
	assert harness.stored_auth_record()['source'] == 'oauth'  # pyright: ignore[reportOptionalSubscript]


def test_a_gate_is_sent_when_the_state_file_cannot_be_written(events, tmp_path, monkeypatch):
	"""A read-only HOME or Lambda: writing the state raised before the send, so the unwritable_store group was never
	counted. The gate is sent, counted in this process, and its first keyed run is reported once."""
	from browser_use.auth import record_auth_event
	from browser_use.telemetry import auth_events as module

	(tmp_path / 'file').write_text('')
	monkeypatch.setattr(module, '_path', lambda: tmp_path / 'file' / 'auth_state.json')  # its dir is a file
	for _ in range(2):
		record_auth_event('missing_key', key_gate='default_model', key_reason='unwritable_store')
	module.keyed_success()
	module.keyed_success()
	assert stages(events) == ['missing_key', 'missing_key', 'keyed_success']
	assert [e['gate_count'] for e in events] == [1, 2, 2]


def test_concurrent_gates_in_one_process_are_all_sent_and_counted(events):
	"""Threads of one process read, count and write the state file under one lock: none is lost or counted twice."""
	from browser_use.auth import record_auth_event

	def gates():
		for _ in range(50):
			record_auth_event('missing_key', key_gate='default_model', key_reason='missing')

	threads = [threading.Thread(target=gates) for _ in range(8)]
	for t in threads:
		t.start()
	for t in threads:
		t.join()
	assert len(stages(events)) == 400
	assert sorted(e['gate_count'] for e in events) == list(range(1, 401))


def test_login_outcomes_are_enums():
	from browser_harness.auth import AuthError

	from browser_use.auth import login_outcome

	assert login_outcome(KeyboardInterrupt()) == 'cancelled'
	assert login_outcome(AuthError('network error: refused')) == 'network'
	assert login_outcome(AuthError('auth failed: access_denied')) == 'denied'
	assert login_outcome(AuthError('expired_token: the code expired')) == 'device_timeout'
	assert login_outcome(AuthError('Browser Use Cloud rejected that key (HTTP 401)')) == 'invalid_key'
	assert login_outcome(AuthError('something else')) == 'error'


def test_key_source_names_where_the_key_comes_from_never_the_key(events, monkeypatch):
	from browser_harness.auth import AuthRecord, save_auth_record

	from browser_use.telemetry.auth_events import key_source

	assert key_source(ChatBrowserUse()) == 'none'
	names = {'oauth': 'login_oauth', 'device_code': 'login_device', 'manual': 'login_manual'}
	for stored in names:
		save_auth_record(AuthRecord(api_key=KEY, source=stored))
		assert key_source(ChatBrowserUse()) == names[stored]
	monkeypatch.setenv('BROWSER_USE_API_KEY', KEY)
	assert key_source(ChatBrowserUse()) == 'env' and key_source('openai:gpt-6-luna') == 'env'
	assert key_source(ChatBrowserUse(api_key=KEY)) == 'param'


def test_login_in_a_notebook_prints_a_device_code_and_opens_nothing(events, monkeypatch, capsys):
	import browser_use

	starts: list[str] = []
	device_code_approves(monkeypatch, starts)
	monkeypatch.setitem(sys.modules, 'ipykernel', SimpleNamespace())
	monkeypatch.setattr('webbrowser.open', lambda *a, **k: pytest.fail('opened a browser from a kernel'))
	browser_use.login()
	out = capsys.readouterr().out
	assert starts == ['device'] and '(code WXYZ-1234)' in out and 'Signed in.' in out
	assert [(e['stage'], e['method']) for e in auth_events_of(events)] == [
		('login_started', 'device'),
		('login_succeeded', 'device'),
	]
	with pytest.raises(ValueError, match='method'):
		browser_use.login('oauth')


async def test_mcp_browser_login_reports_a_failed_login_as_an_error(events, monkeypatch):
	"""browser_login always returned ok=True (mcp_server_event): a denied or timed-out login looked like a success."""
	from mcp import types

	from browser_use.mcp import cli_mcp

	class Denied:
		def __init__(self):
			self.thread = threading.Thread(target=lambda: None)
			self.thread.start()
			self.thread.join()
			self.error, self.opened = 'auth failed: access_denied', False

	monkeypatch.setattr(cli_mcp, '_Login', Denied)
	mcp = cli_mcp.CLIMCPServer()
	handler = mcp.server._request_handlers['tools/call'].handler
	await handler(None, types.CallToolRequestParams(name='browser_login', arguments={}))  # pyright: ignore[reportArgumentType]
	(call,) = (e for e in events if e['event'] == 'mcp_server_event')
	assert (call['tool_name'], call['ok'], call['login_state']) == ('browser_login', False, 'failed')
	# its own error type, not invalid_arguments, and no message: the auth server's error_description is free text
	assert (call['error_type'], call['error_message']) == ('login_failed', None)
	assert 'access_denied' not in json.dumps(events)

	def broken(force):  # a login state is this call's own: the failed one before was reported on this one too
		raise RuntimeError('boom')

	monkeypatch.setattr(mcp, '_sign_in', broken)
	with pytest.raises(RuntimeError):
		await handler(None, types.CallToolRequestParams(name='browser_login', arguments={}))  # pyright: ignore[reportArgumentType]
	assert [e['login_state'] for e in events if e['event'] == 'mcp_server_event'] == ['failed', None]

	output = mcp._execute('start_remote_daemon("browser-use-tests-funnel")')[0]
	assert cli_mcp.LOGIN_HINT in output
	assert [(e['stage'], e['entry'], e['key_gate']) for e in auth_events_of(events)] == [('missing_key', 'mcp', 'mcp_cloud')]
