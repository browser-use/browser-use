"""Telemetry v2 (TELEMETRY.md): counts, names, hostnames and classes are sent; task text, results, code, typed text,
secrets, page content, URL paths/queries/fragments and error messages never are."""

import json
import random
import string
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from conftest import script

from browser_use import Agent, Browser
from browser_use.repl import Repl
from browser_use.telemetry.stats import RunStats, host, imported_modules, scrub_cli_event


def rand(rng: random.Random, n: int = 16) -> str:
	return 'q' + ''.join(rng.choices(string.ascii_letters + string.digits, k=n))


class Page(BaseHTTPRequestHandler):
	def do_GET(self):
		body = b'<title>form</title><input id=f>'
		self.send_response(200)
		self.send_header('Content-Type', 'text/html')
		self.send_header('Content-Length', str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def log_message(self, *args):
		pass


@pytest.fixture(scope='module')
def site():
	server = ThreadingHTTPServer(('127.0.0.1', 0), Page)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	yield f'http://127.0.0.1:{server.server_address[1]}'
	server.shutdown()


@pytest.fixture
def sent(monkeypatch):
	"""The properties each event would send to PostHog."""
	import browser_use.telemetry as telemetry
	import browser_use.telemetry.service as service

	events = []

	class FakeTelemetry:
		def capture(self, event):
			events.append({**event.properties, **service.POSTHOG_EVENT_SETTINGS})

		def flush(self):
			pass

	monkeypatch.setattr(telemetry, 'ProductTelemetry', FakeTelemetry, raising=False)
	return events


def assert_absent(props: dict, *values: str) -> None:
	blob = json.dumps(props, ensure_ascii=False, default=str) + repr(props)
	leaked = [v for v in values if v in blob]
	assert not leaked, f'leaked {leaked}: {props}'


@pytest.mark.parametrize('seed', [1, 2])
async def test_agent_event_never_has_task_secrets_typed_text_code_or_url_paths(seed, chrome, site, sent, tmp_path):
	rng = random.Random(seed)
	task, secret, typed, result, error = (rand(rng) for _ in range(5))
	path, query, value, fragment, other_host = (rand(rng, 10).lower() for _ in range(5))
	url = f'{site}/{path}/{path}2?{query}={value}#{fragment}'
	unresolvable = f'http://{other_host}.invalid/{path}3?{query}=1'
	code = (
		'import json\n'
		f'new_tab({url!r}); wait_for_load()\n'
		'js(\'document.getElementById("f").focus()\')\n'
		f'type_text({typed!r}); type_secret("pw")\n'
		'info = page_info(); print(info)\n'
		"cdp('Runtime.evaluate', expression='1')\n"
		f'goto_url({unresolvable!r})'
	)
	model, _ = script(
		('python', {'code': code}),
		('python', {'code': f'raise ValueError({error!r})'}),
		('finish', {'result': f'{result} {task} {secret}'}),
	)
	agent = Agent(
		f'{task} with {secret}',
		model,
		browser=Browser(cdp_url=chrome['http']),
		sensitive_data={'pw': secret},
		workspace=tmp_path,
	)
	r = await agent.run()
	assert r.status == 'completed', r.error
	(props,) = sent
	assert_absent(props, task, secret, typed, result, error, path, query, value, fragment, 'type_text(', 'wait_for_load()')
	assert props['schema_version'] == 2 and props['agent_type'] == 'pydantic' and props['os']
	assert 'task' not in props and 'final_result_response' not in props and 'error_message' not in props
	assert set(props['domains']) == {'127.0.0.1', f'{other_host}.invalid'} and props['domain_count'] == 2
	h = props['helper_counts']
	assert h['new_tab'] == 1 and h['type_text'] == 1 and h['type_secret'] == 1 and h['page_info'] == 1 and h['goto_url'] == 1
	assert props['cdp_method_counts'] == {'Runtime.evaluate': 1} and props['imports'] == {'json': 1}
	assert props['navigations'] >= 2 and props['cells'] == 2 and props['cell_errors'] == 1
	assert props['cell_error_types'] == {'ValueError': 1} and props['tool_calls'] == {'python': 2, 'finish': 1}
	assert (props['status'], props['success'], props['finish_via'], props['error_type']) == ('completed', True, 'finish', None)
	assert props['sensitive_data_count'] == 1 and props['task_chars'] == len(agent.task) and props['steps'] == 3
	assert (props['browser_mode'], props['cdp_url'], props['keep_alive']) == ('cdp', '127.0.0.1', False)


async def test_failed_run_sends_the_error_class_not_its_message(sent, tmp_path, monkeypatch):
	secret = 'Zq9-unreachable-token-77'

	async def boom():
		raise ConnectionError(f'cannot reach https://intranet.example/{secret}?k={secret}')

	browser = Browser(local=True)
	monkeypatch.setattr(browser, 'start', boom)
	with pytest.raises(ConnectionError):
		await Agent(f'task {secret}', script()[0], browser=browser, workspace=tmp_path).run()
	(props,) = sent
	assert_absent(props, secret, 'intranet', 'cannot reach')
	assert (props['status'], props['error_type'], props['browser_mode'], props['cells']) == (
		'error',
		'ConnectionError',
		'chromium',
		0,
	)


async def test_ultrafast_counts_the_agents_bu_calls_not_the_workers_state_print(daemon, tmp_path):
	repl = Repl(tmp_path, daemon, mode='ultrafast')
	try:
		r = await repl.call('exec', "new_tab('data:text/html,<button>go</button>'); wait_for_load(); bu.state()", 30)
	finally:
		await repl.close()
	assert r['error'] is None, r
	assert r['stats']['helpers'].get('bu.state') == 1 and r['stats']['helpers']['new_tab'] == 1, r['stats']


def test_cell_stats_count_captcha_and_download_events_and_hostnames_only():
	from browser_use.repl.worker import CellStats

	s = CellStats()
	s.observe(
		[
			{'method': 'BrowserUse.captchaSolverStarted', 'params': {}},
			{'method': 'BrowserUse.captchaSolverFinished', 'params': {'success': True}},
			{'method': 'BrowserUse.captchaSolverStarted', 'params': {}},
			{'method': 'BrowserUse.captchaSolverFinished', 'params': {'success': False}},
			{'method': 'Browser.downloadWillBegin', 'params': {'suggestedFilename': 'payroll.csv'}},
			{'method': 'Network.requestWillBeSent', 'params': {}},
			'not an event',
		]
	)
	s.url('https://user:pw@Shop.Example.com:8443/cart/42?token=abc#x', navigation=True)
	s.url('about:blank', navigation=True)
	out = s.take()
	assert out['events'] == {'captcha_started': 2, 'captcha_solved': 1, 'captcha_failed': 1, 'download_started': 1}
	assert (out['hosts'], out['navigations']) == (['shop.example.com'], 1)
	assert s.take()['events'] == {}  # reset per cell

	stats = RunStats()
	stats.add_cell({'error': 'x', 'error_type': 'CellTimeout', 'images': [{}], 'stats': out}, 'import a.b\nfrom c import d', 1.5)
	assert (stats.events['captcha_solved'], stats.error_types, stats.images) == (1, {'CellTimeout': 1}, 1)
	assert dict(stats.imports) == {'a': 1, 'c': 1} and dict(stats.domains) == {'shop.example.com': 1}


def test_cdp_method_counts_keep_only_domain_method_names():
	"""The model can pass a URL or code as cdp()'s method; only Domain.method names reach telemetry."""
	stats = RunStats()
	cdp = {'Page.navigate': 2, 'https://bank.example/acct?token=SENTINEL': 1, 'x = 1; Page.navigate': 1}
	stats.add_cell({'stats': {'cdp': cdp}}, '', 0.1)
	assert dict(stats.cdp_methods) == {'Page.navigate': 2, 'invalid': 2}


def test_page_reads_count_hostnames_only_after_the_agent_navigated():
	"""Browser('chrome') attaches to a tab the user had open: page_info() before any navigation records nothing."""
	from browser_use.repl.worker import CellStats

	s = CellStats()
	s.url('https://mail.example.com/inbox')  # page_info() on the user's own tab
	assert s.take()['hosts'] == []
	s.url('https://shop.example.com/', navigation=True)
	s.url('https://pay.example.com/checkout')  # reached by a click, read with page_info()
	assert s.take()['hosts'] == ['pay.example.com', 'shop.example.com']


@pytest.mark.parametrize('seed', range(20))
def test_host_and_imports_keep_no_path_query_or_code(seed):
	rng = random.Random(seed)
	secret = rand(rng).lower()
	assert host(f'https://{secret[:6]}.example.org/{secret}?{secret}={secret}#{secret}') == f'{secret[:6]}.example.org'
	assert host(f'file:///{secret}') is None and host(f'data:text/html,{secret}') is None and host('http://[::1') is None
	assert imported_modules(f'import os\nprint({secret!r})\nfrom . import {secret}') == ['os']
	assert imported_modules(f'{secret} (') == []


@pytest.mark.parametrize('seed', range(5))
def test_cli_event_drops_piped_code_output_step_args_and_errors(seed):
	rng = random.Random(seed)
	code, out, arg, err = (rand(rng) for _ in range(4))
	payload = {
		'event': 'cli_event',
		'properties': {
			'command': 'script',
			'task': f"type_text('{code}')",
			'task_length': 20,
			'output': out,
			'steps': [
				{'helper': 'goto_url', 'args': f'https://x.test/{arg}'},
				{'helper': 'type_text', 'args': arg, 'error': err},
				{'helper': 'goto_url', 'args': arg},
			],
			'step_count': 3,
			'error_message': err,
		},
	}
	props = scrub_cli_event(payload)['properties']
	assert_absent(props, code, out, arg, err)
	assert props['helper_counts'] == {'goto_url': 2, 'type_text': 1} and props['helper_errors'] == 1
	assert (props['task_length'], props['step_count'], props['command'], props['schema_version']) == (20, 3, 'script', 2)


def test_browser_use_cli_scrubs_what_browser_harness_sends(monkeypatch):
	from browser_harness import telemetry as harness

	import browser_use.cli as cli

	sent_payloads = []
	monkeypatch.setattr(harness, '_send_detached', sent_payloads.append)
	monkeypatch.setattr(harness, 'is_enabled', lambda: True)
	monkeypatch.setattr(harness, '_install_id', lambda *a, **k: 'test-install')  # never writes the real config
	cli._scrub_harness_telemetry()
	cli._scrub_harness_telemetry()  # idempotent: one scrub layer
	harness.capture_cli_event(
		action='completed', command='script', task='type_text("Zq9-typed")', output='Zq9-out', steps=[{'helper': 'js'}]
	)
	(payload,) = sent_payloads
	assert_absent(payload, 'Zq9-typed', 'Zq9-out')
	assert payload['properties']['task_length'] == len('type_text("Zq9-typed")')
	assert payload['properties']['helper_counts'] == {'js': 1}


def test_posthog_client_sends_no_exceptions_and_respects_opt_out(monkeypatch):
	import posthog

	import browser_use.telemetry.service as service
	from browser_use.telemetry.views import AgentTelemetryEvent

	cls = type(service.ProductTelemetry())  # the singleton's class: build fresh instances
	made, captured = [], []

	class FakePosthog:
		def __init__(self, **kwargs):
			made.append(kwargs)

		def capture(self, **kwargs):
			captured.append(kwargs)

	monkeypatch.setattr(posthog, 'Posthog', FakePosthog)
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'true')
	cls().capture(AgentTelemetryEvent(version='1', source='pip', model='m'))
	assert made[0]['enable_exception_autocapture'] is False
	assert captured[0]['event'] == 'agent_event' and captured[0]['properties']['model'] == 'm'
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'false')
	off = cls()
	off.capture(AgentTelemetryEvent(version='1', source='pip'))
	assert off._posthog_client is None and len(captured) == 1


def test_install_source_reads_package_metadata(monkeypatch):
	import importlib.metadata

	from browser_use.utils import get_install_source

	class Dist:
		def __init__(self, files):
			self.files = files

		def read_text(self, name):
			return self.files.get(name)

	cases = [
		({'direct_url.json': '{"url": "file:///x", "dir_info": {"editable": true}}'}, 'editable'),
		({'direct_url.json': '{"url": "git+https://x", "vcs_info": {"vcs": "git"}}'}, 'git'),
		({'INSTALLER': 'uv\n'}, 'uv'),
		({}, 'unknown'),
	]
	for files, expected in cases:
		monkeypatch.setattr(importlib.metadata, 'distribution', lambda name, files=files: Dist(files))
		get_install_source.cache_clear()
		assert get_install_source() == expected
	get_install_source.cache_clear()


async def test_follow_up_counts_only_its_own_turns_and_cloud_downloads_by_extension(sent, tmp_path, monkeypatch):
	from pathlib import Path

	async def start(self):
		return {}

	async def stop(self, downloads_dir=None):
		return [Path(downloads_dir) / 'Payroll Q3.CSV', Path(downloads_dir) / 'invoice-77.pdf']

	monkeypatch.setattr(Browser, 'start', start)
	monkeypatch.setattr(Browser, 'stop', stop)
	model, _ = script(('python', {'code': 'x = 1'}), ('finish', {'result': 'one'}), ('finish', {'result': 'two'}))
	agent = Agent('first', model, browser=Browser(local=True), workspace=tmp_path)
	await agent.run()
	agent.add_new_task('second')
	await agent.run()
	first, second = sent
	assert (first['tool_calls'], first['follow_up'], first['cells']) == ({'python': 1, 'finish': 1}, False, 1)
	assert (second['tool_calls'], second['follow_up'], second['cells']) == ({'finish': 1}, True, 0)
	assert second['downloads'] == 2 and second['download_exts'] == {'csv': 1, 'pdf': 1}
	assert_absent(second, 'Payroll', 'invoice-77')
