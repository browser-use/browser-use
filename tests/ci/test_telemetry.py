"""Telemetry v4: counts, names, timings, hostnames and classes, the URLs visited without query strings, error messages
and the final result are sent, scrubbed of secrets, emails and credentials; the task text, typed text, code, secrets,
query strings and fragments never are. Recording costs microseconds, sending happens off the agent path,
ANONYMIZED_TELEMETRY=false sends and writes nothing."""

import atexit
import gzip
import importlib.util
import json
import os
import random
import re
import socket
import statistics
import string
import subprocess
import sys
import threading
import time
import uuid
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import script

import browser_use
from browser_use import Agent, Browser
from browser_use.repl import Repl
from browser_use.telemetry.stats import (
	RunStats,
	cdp_category,
	error_class,
	host,
	imported_modules,
	page_url,
	scrub,
	scrub_cli_event,
)


def rand(rng: random.Random, n: int = 16) -> str:
	return 'q' + ''.join(rng.choices(string.ascii_letters + string.digits, k=n))


def slug(rng: random.Random, n: int = 10) -> str:
	"""An ordinary URL path segment: letters and digits mixed, 12 or more, are a token (sent as <token>)."""
	return 'q' + ''.join(rng.choices(string.ascii_lowercase, k=n))


HELPER_FILE = str(Path(browser_use.__file__).resolve().parent / 'helper_sim.py')


def lib_raise(exception: str) -> str:
	"""Cell code whose exception a browser-use helper raises: its message is sent, scrubbed. What the cell's own code
	or any other library raises is sent as its class only (stats.raised_by_cell)."""
	return f'exec(compile({"raise " + exception!r}, {HELPER_FILE!r}, "exec"))'


class Page(BaseHTTPRequestHandler):
	def do_GET(self):
		title = parse_qs(urlsplit(self.path).query).get('t', ['form'])[0]  # a page title the agent reads
		body = f'<title>{title}</title><input id=f>'.encode()
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
	"""The properties each agent_event would send, built as the telemetry thread builds them."""
	import browser_use.telemetry.service as service

	events = []

	class FakeTelemetry:
		enabled = True

		def run_started(self, run_id, props, progress):
			pass

		def capture_run(self, job):
			events.append(job.build(200, 50))

		def capture(self, event):
			events.append({'event': event.name, **event.properties})

	monkeypatch.setattr(service, 'telemetry', FakeTelemetry)
	return events


@pytest.fixture
def posthog(monkeypatch, tmp_path):
	"""A local PostHog: the real sender (thread, gzip, /batch/) posts here. events() waits for n agent_events. With
	down set it answers 503 and keeps nothing; attempts counts the /batch/ posts either way."""
	import browser_use.telemetry.service as service
	from browser_use.telemetry import feedback

	monkeypatch.setattr(feedback, '_mcp_sent', 0)  # browser_feedback's per-process cap: each test is a new server
	bodies: list[str] = []
	state = SimpleNamespace(down=False, attempts=0)

	class Capture(BaseHTTPRequestHandler):
		def do_POST(self):
			raw = self.rfile.read(int(self.headers['Content-Length']))
			if len(raw) < int(self.headers['Content-Length']):  # a sender frozen mid-POST at its exit: nothing arrived
				return
			if self.path.startswith('/batch/'):
				state.attempts += 1
			if state.down:
				self.send_response(503)
				self.end_headers()
				return
			bodies.append((gzip.decompress(raw) if self.headers.get('Content-Encoding') == 'gzip' else raw).decode())
			self.send_response(200)
			self.end_headers()
			self.wfile.write(b'{"status": 1}')

		def log_message(self, *args):
			pass

	server = ThreadingHTTPServer(('127.0.0.1', 0), Capture)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	config = tmp_path / 'config'
	monkeypatch.setattr(service, 'POSTHOG_HOST', f'http://127.0.0.1:{server.server_address[1]}')
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'true')
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(config))
	monkeypatch.setenv('BROWSER_USE_DEVICE_ID', 'bu-test-device')
	monkeypatch.setattr(service, '_device_id', None)
	instance = service.ProductTelemetry()
	monkeypatch.setattr(service, '_instance', instance)

	def events(n: int = 1, timeout: float = 15) -> list[dict]:
		deadline = time.monotonic() + timeout
		while time.monotonic() < deadline:
			got = [e for b in list(bodies) for e in json.loads(b)['batch']]
			if len(got) >= n:
				return got
			time.sleep(0.02)
		raise AssertionError(f'{len(bodies)} bodies arrived, wanted {n} events')

	yield SimpleNamespace(bodies=bodies, events=events, telemetry=instance, config=config, server=server, state=state)
	instance._pending.clear()
	atexit.unregister(instance._at_exit)
	# a thread left running wrote its failed send into the next test's outbox and retried to the next test's PostHog
	stopped = instance.stop()
	server.shutdown()
	assert stopped, 'the telemetry thread outlived its test'


@pytest.fixture
def dead_posthog(posthog, monkeypatch):
	"""A PostHog that accepts and never answers: an event stays queued. Closed at teardown, before posthog waits for the
	thread, which ends the sends in flight."""
	import browser_use.telemetry.service as service

	with socket.create_server(('127.0.0.1', 0)) as server:
		monkeypatch.setattr(service, 'POSTHOG_HOST', f'http://127.0.0.1:{server.getsockname()[1]}')
		yield posthog


def no_browser(monkeypatch) -> None:
	async def start(self):
		return {}

	async def stop(self, downloads_dir=None):
		return []

	monkeypatch.setattr(Browser, 'start', start)
	monkeypatch.setattr(Browser, 'stop', stop)


def assert_absent(props: dict, *values: str) -> None:
	blob = json.dumps(props, ensure_ascii=False, default=str) + repr(props)
	leaked = [v for v in values if v in blob]
	assert not leaked, f'leaked {leaked}: {props}'


@pytest.mark.parametrize('seed', [1, 2])
async def test_agent_event_sends_urls_errors_and_result_never_task_secrets_typed_text_code_or_queries(
	seed, chrome, site, sent, tmp_path
):
	rng = random.Random(seed)
	task, secret, typed, result, error = (rand(rng) for _ in range(5))
	query, value, fragment, other_host = (rand(rng, 10).lower() for _ in range(4))
	path = slug(rng, 8)  # {path}2 stays under 12 letters and digits
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
		('finish', {'success': True, 'result': f'{result} {task} with {secret}'}),
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
	assert_absent(props, task, secret, typed, query, value, fragment, error, 'type_text(', 'wait_for_load()')
	assert props['schema_version'] == 4 and props['agent_type'] == 'pydantic' and props['os']
	assert 'task' not in props and 'final_result_response' not in props
	assert props['urls_visited'] == [f'http://127.0.0.1/{path}/{path}2', f'http://{other_host}.invalid/{path}3']  # no port
	assert props['error_messages'] == ['ValueError']  # the cell raised it with what it read: its class, never the message
	assert props['final_result'] == f'{result} <task>'  # the result quoted the task, its secret redacted
	assert set(props['domains']) == {'127.0.0.1', f'{other_host}.invalid'} and props['domain_count'] == 2
	h = props['helper_counts']
	assert h['new_tab'] == 1 and h['type_text'] == 1 and h['type_secret'] == 1 and h['page_info'] == 1 and h['goto_url'] == 1
	assert props['cdp_method_counts'] == {'Runtime.evaluate': 1} and props['imports'] == {'json': 1}
	assert props['navigations'] >= 2 and props['cells'] == 2 and props['cell_errors'] == 1
	assert props['cell_error_types'] == {'ValueError': 1} and props['tool_calls'] == {'python': 2, 'finish': 1}
	assert (props['status'], props['success'], props['finish_via'], props['error_type']) == ('completed', True, 'finish', None)
	assert props['sensitive_data_count'] == 1 and props['task_chars'] == len(agent.task) and props['steps'] == 3
	assert (props['browser_mode'], props['cdp_url'], props['keep_alive']) == ('cdp', 'localhost', False)


async def test_a_made_up_tool_name_is_sent_as_invalid(sent, chrome, tmp_path):
	"""tool_calls counted every tool name the model wrote, verbatim and uncapped: a hallucinated name carrying task or
	page text reached PostHog. Names outside the agent's tools are now 'invalid'."""
	from browser_use import Tools

	tools = Tools()

	@tools.action('Look up a price')
	def price(sku: str) -> str:
		return '7'

	made_up = 'send_acme_payroll_to_jane_doe_ssn_123_45_6789_' + 'x' * 100
	model = script((made_up, {'a': 1}), ('price', {'sku': 'a'}), ('finish', {'success': True, 'result': 'ok'}))[0]
	await Agent('t', model, browser=Browser(cdp_url=chrome['http']), tools=tools, workspace=tmp_path).run()
	(props,) = sent
	assert props['tool_calls'] == {'invalid': 1, 'price': 1, 'finish': 1}
	assert_absent(props, 'ssn', 'payroll')


async def test_failed_run_sends_the_error_class_and_its_message_with_secrets_redacted(sent, tmp_path, monkeypatch):
	secret = 'Zq9-unreachable-token-77'

	async def boom():
		raise ConnectionError(f'cannot reach https://intranet.example/{secret}?k={secret}')

	browser = Browser(local=True)
	monkeypatch.setattr(browser, 'start', boom)
	agent = Agent(f'task {secret}', script()[0], browser=browser, sensitive_data={'tok': secret}, workspace=tmp_path)
	result = await agent.run()
	assert result.status == 'error'  # a failed browser start is a result, never raised (error contract)
	(props,) = sent
	assert_absent(props, secret)
	assert props['error_messages'] == ['cannot reach https://intranet.example/<secret:tok>']  # no query
	assert (props['status'], props['error_type'], props['browser_mode'], props['cells']) == (
		'error',
		'ConnectionError',
		'chromium',
		0,
	)


async def test_a_rejected_key_sends_preflight_error_not_none(sent, tmp_path, monkeypatch):
	"""C55: a key or model check that failed before the browser started was sent as error_type=None."""
	secret = 'sk-rejected-Zq9'
	monkeypatch.setattr('browser_use.agent.service.provider_preflight', lambda model: f'rejected the API key: {secret}')
	result = await Agent('t', script()[0], browser=Browser(local=True), workspace=tmp_path).run()
	(props,) = sent
	assert result.status == 'error' and (props['status'], props['error_type']) == ('error', 'PreflightError')
	assert props['error_messages'] == ['rejected the API key: <credential>']  # a key in a message is a credential
	assert_absent(props, secret)


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
			{'method': 'Browser.downloadWillBegin', 'params': {'guid': 'g1', 'suggestedFilename': 'payroll.csv'}},
			{'method': 'Page.downloadWillBegin', 'params': {'guid': 'g1', 'suggestedFilename': 'payroll.csv'}},
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
	stats.add_cell(
		{'error': 'x', 'error_type': 'CellTimeout', 'images': [{}], 'stats': out}, 'import os.path\nfrom json import d', 1.5
	)
	assert (stats.events['captcha_solved'], stats.error_types, stats.images) == (1, {'CellTimeout': 1}, 1)
	assert dict(stats.imports) == {'os': 1, 'json': 1} and dict(stats.domains) == {'shop.example.com': 1}


def test_one_download_announced_by_both_events_counts_once():
	"""Cloud browsers send Browser.downloadWillBegin and Page.downloadWillBegin for one download: telemetry said 2."""
	from browser_use.repl.worker import CellStats

	s = CellStats()
	s.observe([{'method': 'Browser.downloadWillBegin', 'params': {'guid': 'g1'}}])
	assert s.take()['events'] == {'download_started': 1}
	s.observe([{'method': 'Page.downloadWillBegin', 'params': {'guid': 'g1'}}])  # its twin, read in a later cell
	s.observe([{'method': m, 'params': {'guid': 'g2'}} for m in ('Page.downloadWillBegin', 'Browser.downloadWillBegin')])
	assert s.take()['events'] == {'download_started': 1}


@pytest.mark.parametrize('seed', range(5))
def test_names_the_models_code_chooses_are_kept_only_when_python_or_a_package_defines_them(seed):
	"""Telemetry rerun #9: a module, exception class or cdp() method named by the model's code went out verbatim, a
	channel a prompt-injected page could use to send text out."""
	secret = rand(random.Random(seed))
	assert imported_modules(f'import {secret}\nimport json\nfrom PIL import Image') == ['other', 'json', 'PIL']
	stats = RunStats()
	stats.add_cell({'stats': {'cdp': {f'Page.{secret}': 1, f'{secret}.navigate': 1, 'Page.navigate': 1}}}, '', 0.1)
	assert dict(stats.cdp_methods) == {'invalid': 2, 'Page.navigate': 1}
	custom = type(secret, (ValueError,), {})  # what `class <secret>(ValueError)` in a cell makes
	assert error_class(custom()) == 'custom' and error_class(KeyError()) == 'KeyError'
	assert error_class(json.JSONDecodeError('x', 'y', 0)) == 'JSONDecodeError'
	fake = type(secret, (ValueError,), {'__module__': 'json'})  # claims a stdlib module it is not in
	assert error_class(fake()) == 'custom'
	double = type(secret, (fake,), {'__module__': 'json'})  # a subclass named after it: still not json's
	assert error_class(double()) == 'custom'


async def test_a_cells_custom_exception_class_is_sent_as_custom(tmp_path):
	repl = Repl(tmp_path)
	try:
		r = await repl.call('exec', 'class ZqSmuggledText(Exception): pass\nraise ZqSmuggledText()', 30)
	finally:
		await repl.close()
	assert r['error_type'] == 'custom' and 'ZqSmuggledText' in r['error']  # the model still sees it


@pytest.mark.parametrize(
	'hostname, kind',
	[
		('0a1b2c3d-4e5f-6789-abcd-ef0123456789.cdp.browser-use.com', 'browser-use-cloud'),
		('127.0.0.1', 'localhost'),
		('localhost', 'localhost'),
		('::1', 'localhost'),
		('192.168.1.20', 'private'),
		('10.0.0.5', 'private'),
		('chrome', 'private'),
		('browser.internal', 'private'),
		('connect.example.test', 'public-other'),
		('8.8.8.8', 'public-other'),
		(None, None),
	],
)
def test_cdp_url_is_sent_as_its_kind_never_its_hostname(hostname, kind):
	"""Telemetry P1: a Browser Use cloud cdpUrl's hostname is the browser id, which alone drives the live browser."""
	assert cdp_category(hostname) == kind
	payload = scrub_cli_event({'properties': {'cdp_url': hostname}})
	assert payload['properties']['cdp_url'] == kind


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


@pytest.mark.parametrize(
	'url',
	[
		'https://zq best flights for jane doe/',  # a weak model passes the task as the URL
		'https://zq%20jane%20doe.example.com/',
		'javascript://zqalert(document.cookie)',
		'chrome-extension://zqextensionid/popup.html',
		'https://zq\u00e9|jane!.com/',
	],
)
def test_a_navigation_to_text_that_is_not_a_hostname_records_no_host(url):
	"""Privacy red team: urlsplit() returns any text between // and the next / as the hostname, so goto_url() with the
	task in place of a URL put that text into domains, host_stats and s_host."""
	from browser_use.repl.worker import CellStats

	assert host(url) is None
	s = CellStats()
	s.url(url, navigation=True)
	assert s.take()['hosts'] == []


def test_host_keeps_real_hostnames_and_ips():
	assert host('https://Shop.Example.com:8443/a') == 'shop.example.com'
	assert host('https://b\u00fccher.example/') == 'xn--bcher-kva.example'
	assert host('https://x.com\\@zqother.example/') == 'x.com'  # Chrome reads a backslash as a slash
	assert host('http://[::1]:9222/json') == '::1' and host('ws://chrome:9222/devtools') == 'chrome'
	assert host('http://192.168.1.20/') == '192.168.1.20' and host('https://my_host.internal/') == 'my_host.internal'


@pytest.mark.parametrize(
	'url, sent',
	[
		('https://zq-quiet-river.trycloudflare.com/admin', '*.trycloudflare.com'),
		('https://zq1a2b3c.ngrok-free.app/', '*.ngrok-free.app'),
		('https://zq1a2b3c.ngrok.io/', '*.ngrok.io'),
		('https://zq1a2b3c.ngrok.app/', '*.ngrok.app'),
		('https://zq-tidy-cat.loca.lt/', '*.loca.lt'),
		('https://zqabc123def.lambda-url.us-east-1.on.aws/', '*.lambda-url.us-east-1.on.aws'),
		('https://zqshop-k3j2h1g0f-acme.vercel.app/', '*.vercel.app'),
		('https://zqshop-git-fix-login-acme.vercel.app/', '*.vercel.app'),
		('https://deploy-preview-42--zqsite.netlify.app/', '*.netlify.app'),
		('https://zq-user-repo-5x7.github.dev/', '*.github.dev'),
		('https://zq-user-repo-5x7-3000.app.github.dev/', '*.app.github.dev'),
		('https://8080-zquser-repo-ab12.ws-eu110.gitpod.io/', '*.gitpod.io'),
		('https://zqapp.zquser.repl.co/', '*.repl.co'),
		('https://zq4f9k2.csb.app/', '*.csb.app'),
		('https://myapp.vercel.app/', 'myapp.vercel.app'),  # a production deploy: public
		('https://mysite.netlify.app/', 'mysite.netlify.app'),
		('https://github.dev/', 'github.dev'),
	],
)
def test_a_hostname_that_alone_grants_access_is_sent_as_its_provider(url, sent):
	"""Privacy red team: a tunnel to the developer's machine, a cloud IDE's forwarded port, a Lambda function URL or a
	preview deploy is reachable by whoever knows its name, and domains, host_stats and s_host sent that name."""
	from browser_use.repl.worker import CellStats

	assert host(url) == sent
	s = CellStats()
	s.url(url, navigation=True)
	assert s.take()['hosts'] == [sent]
	assert cdp_category(host(url.replace('https', 'wss'))) == 'public-other'


def test_a_custom_endpoint_sends_the_provider_name_not_its_base_url_and_a_local_model_path_as_its_last_segment():
	"""Privacy red team: a Pydantic AI model passed as llm= put its Provider object in model_provider. asdict() could not
	copy it (an RLock), so the run sent no event; a Provider that copies would send 'OpenAIProvider(name=openai,
	base_url=https://...)'. A vLLM model named by its path sent the path (a user name)."""
	from pydantic_ai.models.openai import OpenAIChatModel
	from pydantic_ai.providers.openai import OpenAIProvider

	from browser_use.telemetry.views import AgentTelemetryEvent

	provider = OpenAIProvider(base_url='https://zqtenant.internal.example/v1/zqaccount', api_key='sk-zqsecret')
	agent = Agent('t', llm=OpenAIChatModel('/home/zqjane/ckpt/Llama-3-8B', provider=provider))
	agent._build()
	props = AgentTelemetryEvent('1.0', 'pip', **agent._config(10, 60)).properties
	assert (props['model'], props['model_provider']) == ('Llama-3-8B', 'openai')
	assert_absent(props, 'zqtenant', 'zqaccount', 'zqsecret', 'zqjane', 'ckpt')


def test_an_api_key_passed_as_the_model_name_is_sent_as_other():
	"""Privacy red team: ChatOpenAI(os.environ['OPENAI_API_KEY']) (the key where the model goes) sent the key's first 64
	characters as model, on the PreflightError event the bad model produced. Real model ids are kept."""
	from browser_use import ChatOpenAI
	from browser_use.telemetry.stats import model_id
	from browser_use.telemetry.views import AgentTelemetryEvent

	key = 'sk-proj-' + 'Zq7' * 30
	agent = Agent('t', llm=ChatOpenAI(key, api_key='sk-test'))
	agent._build()
	props = AgentTelemetryEvent('1.0', 'pip', **agent._config(10, 60)).properties
	assert props['model'] == 'other'
	assert_absent(props, 'Zq7Zq7')
	keys = ('sk-ant-api03-' + 'a1B2' * 20, 'AIzaSyD' + 'x9' * 16, 'AQ.' + 'Ab3' * 20, 'bu_' + 'k8' * 20, 'xai-' + 'Q1' * 20)
	keys += ('openai:sk-' + 'w' * 20, 'hf_' + 'abc' * 10, 'gsk_' + 'z' * 20, 'eyJhbGciOiJIUzI1NiJ9.e30.x', 'A1b2' * 10)
	assert [model_id(k) for k in keys] == ['other'] * len(keys)
	assert scrub_cli_event({'properties': {'model': key}})['properties']['model'] == 'other'
	kept = ('bu-fast', 'gpt-6-luna', 'openai/gpt-5', 'claude-opus-5', 'gemini-3-flash-preview', 'Llama-3-8B', 'grok-5')
	kept += ('ft:gpt-4o-mini-2024-07-18:acme:support:9xYz12Ab', 'meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo')
	kept += ('accounts/fireworks/models/llama-v3p1-70b-instruct', 'us.anthropic.claude-sonnet-4-5-20250929-v1:0')
	assert [model_id(k) for k in kept] == list(kept)


def test_a_download_extension_is_sent_only_when_it_is_a_common_file_type():
	"""Privacy red team: a downloaded file's name is the site's, and 'Statement.Jane Doe 2026' sent 'jane doe '."""
	from browser_use.telemetry.stats import download_ext

	assert [download_ext(Path(n)) for n in ('a.PDF', 'b.tar.gz', 'c', 'd.xlsx')] == ['pdf', 'gz', 'none', 'xlsx']
	assert download_ext(Path('Statement.Zqjane Doe 2026')) == 'other' and download_ext(Path('x.zqsecret')) == 'other'


def test_imports_of_a_cell_with_an_invalid_escape_print_nothing_on_the_users_stderr():
	"""C60: the parent parses each cell for telemetry; a non-raw regex printed '<unknown>:1: SyntaxWarning' to the
	user's terminal. The worker's compile still shows the model its own warning."""
	with warnings.catch_warnings(record=True) as caught:
		warnings.simplefilter('always', SyntaxWarning)
		assert imported_modules("import re\nre.findall('\\d+', 'a1')") == ['re']
	assert not [w for w in caught if w.category is SyntaxWarning]


@pytest.mark.parametrize('seed', range(5))
def test_cli_event_drops_piped_code_output_and_step_args_and_sends_the_error_line(seed):
	rng = random.Random(seed)
	code, out, arg, err, frame = (rand(rng) for _ in range(5))
	traceback = f'Traceback (most recent call last):\n  File "<stdin>", line 1, in <module>\n    {frame}()\n'
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
			'error_message': f'{traceback}ValueError: {err} key sk-{arg}\n',
		},
	}
	props = scrub_cli_event(payload)['properties']
	assert_absent(props, code, out, arg, frame)
	assert props['error_message'] == f'ValueError: {err} key <credential>'
	assert props['helper_counts'] == {'goto_url': 2, 'type_text': 1} and props['helper_errors'] == 1
	assert (props['task_length'], props['step_count'], props['command'], props['schema_version']) == (20, 3, 'script', 3)


def test_browser_use_cli_scrubs_what_browser_harness_sends(monkeypatch, sent):
	from browser_harness import telemetry as harness

	import browser_use.cli as cli

	monkeypatch.setattr(harness, '_send_detached', harness._send_detached)  # restored after the test, wrapper and all
	monkeypatch.setattr(harness, 'is_enabled', lambda: True)
	monkeypatch.setattr(harness, '_install_id', lambda *a, **k: 'test-install')  # never writes the real config
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'true')
	cli._scrub_harness_telemetry()
	cli._scrub_harness_telemetry()  # idempotent: one scrub layer
	harness.capture_cli_event(
		action='completed', command='script', task='type_text("Zq9-typed")', output='Zq9-out', steps=[{'helper': 'js'}]
	)
	(props,) = sent
	assert_absent(props, 'Zq9-typed', 'Zq9-out')
	assert props['task_length'] == len('type_text("Zq9-typed")')
	assert props['helper_counts'] == {'js': 1}


def test_cli_event_sends_only_the_class_of_an_error_the_piped_code_raised(monkeypatch, sent):
	"""Retest 1.0.1: the CLI sent the message the piped code's own raise wrote (`assert 'Paid' in text, text[:300]`),
	page text no scrub knows; --cli-mcp sent only its class. A library the code called can quote it too (json, strptime):
	class only. Only browser-use's and browser-harness's own errors keep their scrubbed message."""
	from browser_harness import telemetry as harness

	import browser_use.cli as cli

	monkeypatch.setattr(harness, '_send_detached', harness._send_detached)  # restored after the test, wrapper and all
	monkeypatch.setattr(harness, 'is_enabled', lambda: True)
	monkeypatch.setattr(harness, '_install_id', lambda *a, **k: 'test-install')
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'true')
	cli._scrub_harness_telemetry()
	for code in ('text = "Zq9 Jane Doe"\nassert "Paid" in text, text', 'import json\njson.loads("{Zq9")'):
		try:
			exec(code, {})  # as browser-harness's run.py runs the piped code
		except Exception as exc:  # and sends its event while it handles the error (run.main)
			harness.capture_cli_event(action='error', command='script', exit_code=1, error_message=str(exc))
	assert_absent({'events': sent}, 'Zq9')
	assert [p['error_message'] for p in sent] == ['AssertionError', 'JSONDecodeError']


def test_cli_event_goes_to_the_library_project_under_the_device_id(posthog, monkeypatch, tmp_path, caplog):
	"""Retest 11-09: the browser-use CLI's cli_event (`--cli-mcp` and `--mcp` included) went to the browser-harness
	PostHog project under a browser-harness install id, agent_event to the library project under the browser-use device
	id: CLI and MCP usage never showed next to the same machine's library runs, and BROWSER_USE_DEVICE_ID did not apply."""
	from browser_harness import telemetry as harness

	import browser_use.cli as cli
	import browser_use.telemetry.service as service

	harness_sends = []
	monkeypatch.setenv('BH_CONFIG_DIR', str(tmp_path / 'bh'))  # never the developer's own browser-harness config
	for name in ('BH_TELEMETRY', 'BROWSER_HARNESS_TELEMETRY'):
		monkeypatch.delenv(name, raising=False)
	monkeypatch.setattr(harness, '_send_detached', harness_sends.append)
	monkeypatch.setattr(harness, '_install_id', harness._install_id)  # restored after the test, wrapper and all
	cli._scrub_harness_telemetry()
	harness.capture_cli_event(action='completed', command='cli-mcp', task='print("Zq9-code")', steps=[{'helper': 'js'}])
	(event,) = posthog.events()
	assert not harness_sends
	assert json.loads(posthog.bodies[0])['api_key'] == service.POSTHOG_PROJECT_API_KEY
	assert (event['event'], event['distinct_id']) == ('cli_event', 'bu-test-device')
	props = event['properties']
	assert (props['command'], props['helper_counts'], props['is_internal'], props['$lib']) == (
		'cli-mcp',
		{'js': 1},
		True,
		'browser-use',
	)
	assert_absent(props, 'Zq9-code')
	assert not [p for p in tmp_path.joinpath('bh').rglob('*') if p.is_file()]  # nor a browser-harness install id
	assert 'anonymized usage telemetry' not in caplog.text  # the CLI's stderr: no notice on every command


def test_a_failed_cli_command_sends_its_error_message(monkeypatch, sent):
	"""cli_event's error_message is what tells a failing CLI call apart in production: a command that fails before
	browser-harness runs sends its error line too, not only the exit code."""
	from browser_harness import telemetry as harness

	import browser_use.cli as cli

	for attr in ('_send_detached', '_install_id', 'is_enabled', 'status'):  # restored after the test, wrappers and all
		monkeypatch.setattr(harness, attr, getattr(harness, attr))
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'true')
	monkeypatch.setenv('BROWSER_USE_DEVICE_ID', 'bu-test-device')
	monkeypatch.setattr(sys, 'argv', ['browser-use', '--update'])
	assert cli.main() == 2
	(props,) = sent
	assert (props['command'], props['action'], props['exit_code']) == ('update', 'error', 2)
	assert (
		props['error_message']
		== 'browser-use does not update itself: uv tool upgrade browser-use (or pip install -U browser-use).'
	)


async def test_each_mcp_tool_call_sends_an_event(sent, monkeypatch):
	"""Retest 11-09: 0.x's MCP server sent one mcp_server_event per tool call (tool, duration) to the library project;
	1.0's --cli-mcp sent one cli_event, to the browser-harness project, when the session ended: which tools MCP clients
	call, how long they take and how often they fail went unmeasured, and a server its client killed sent nothing."""
	from mcp import types

	from browser_use.mcp import cli_mcp

	monkeypatch.setenv('BROWSER_USE_TELEMETRY_INTERNAL', '1')
	monkeypatch.setenv('CLAUDECODE', '1')
	mcp = cli_mcp.CLIMCPServer()
	mcp._ensure_daemon = lambda code: None  # the cells below need no browser
	handler = mcp.server._request_handlers['tools/call'].handler
	calls = [
		('browser_exec', {'code': 'print("Zq9-out")'}),
		('browser_exec', {'code': 'raise KeyError("sent zq7 sk-ant-Zq9secretkey123")'}),
		('browser_exec', {'code': 'import json\njson.loads("{Zq9")'}),
		('browser_exec', {'code': ''}),
		('browser_navigate', {'url': 'https://zq9.test/'}),
		('Zq9-made-up', {}),
	]
	for name, arguments in calls:
		await handler(None, types.CallToolRequestParams(name=name, arguments=arguments))  # pyright: ignore[reportArgumentType]
	assert_absent({'events': sent}, 'Zq9')
	# what the cell's code or a library it called raised is its class only: it can quote what Claude typed or read from
	# the page. A rejected call has no exception: its error is the server's own text; an unknown tool's name is never sent
	errors = [e['error_message'] for e in sent]
	assert errors == [None, None, None, "'code' must be a non-empty string", None, None]
	got = [(e['event'], e['action'], e['tool_name'], e['ok'], e['error_type'], e['call_n']) for e in sent]
	assert got == [
		('mcp_server_event', 'tool_call', 'browser_exec', True, None, 1),
		('mcp_server_event', 'tool_call', 'browser_exec', False, 'KeyError', 2),
		('mcp_server_event', 'tool_call', 'browser_exec', False, 'JSONDecodeError', 3),
		('mcp_server_event', 'tool_call', 'browser_exec', False, 'invalid_arguments', 4),
		('mcp_server_event', 'tool_call', 'browser_navigate', False, 'unknown_tool', 5),
		('mcp_server_event', 'tool_call', 'invalid', False, 'unknown_tool', 6),
	]
	first = sent[0]
	assert (first['server'], first['browser'], first['agent_client'], first['is_internal']) == (
		'cli-mcp',
		'chrome',
		'claude-code',
		True,
	)
	assert 0 <= first['duration_seconds'] < 30 and first['version'] and first['os']


@pytest.mark.parametrize('internal', ['1', ''])
def test_cli_event_is_marked_internal_like_the_agent_event(monkeypatch, internal):
	"""Release smoke 11-09: BROWSER_USE_TELEMETRY_INTERNAL marked our evals' and tests' agent_event, never their
	cli_event: CLI and MCP usage from our own CI and agents could not be told apart from users'."""
	monkeypatch.setenv('BROWSER_USE_TELEMETRY_INTERNAL', internal)
	props = scrub_cli_event({'event': 'cli_event', 'properties': {'command': 'script'}})['properties']
	assert props['is_internal'] is bool(internal)


@pytest.mark.parametrize('value, sends', [('n', False), ('disable', False), ('on', False), ('0', False), ('yes', True)])
def test_cli_opt_out_values_match_the_library(monkeypatch, sent, value, sends):
	"""Any value not starting with t, y or 1 turns it off. browser-harness alone sent with n, disable."""
	from browser_harness import telemetry as harness

	import browser_use.cli as cli

	monkeypatch.setattr(harness, '_send_detached', harness._send_detached)
	monkeypatch.setattr(harness, '_install_id', lambda *a, **k: 'test-install')
	monkeypatch.setattr(harness, 'is_enabled', lambda: not harness._env_disabled())  # never reads the real config
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', value)
	cli._scrub_harness_telemetry()
	harness.capture_cli_event(action='completed', command='version')
	assert bool(sent) is sends


@pytest.mark.parametrize('value', ['n', 'disable'])
def test_cli_opt_out_writes_no_browser_harness_install_id(monkeypatch, sent, tmp_path, value):
	"""Clean-install smoke 11-09: ANONYMIZED_TELEMETRY=n (off) sent nothing, but `browser-use --version`
	still wrote ~/.config/browser-harness/telemetry.json with a new install id: browser-harness only knows 0, false, no
	and off, and built the event (creating the id) before the browser-use wrapper dropped the send. Off means no file."""
	from browser_harness import telemetry as harness

	import browser_use.cli as cli

	monkeypatch.setenv('BH_CONFIG_DIR', str(tmp_path / 'bh'))
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path / 'bu'))
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', value)
	for name in ('BH_TELEMETRY', 'BROWSER_HARNESS_TELEMETRY'):
		monkeypatch.delenv(name, raising=False)
	# restored after the test, wrappers and all
	monkeypatch.setattr(harness, '_send_detached', harness._send_detached)
	monkeypatch.setattr(harness, '_install_id', harness._install_id)
	monkeypatch.setattr(harness, 'is_enabled', harness.is_enabled)
	cli._scrub_harness_telemetry()
	harness.capture_cli_event(action='completed', command='version')
	assert not sent
	assert not [p for p in tmp_path.rglob('*') if p.is_file()]


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
	model, _ = script(
		('python', {'code': 'x = 1'}),
		('finish', {'success': True, 'result': 'one'}),
		('finish', {'success': True, 'result': 'two'}),
	)
	agent = Agent('first', model, browser=Browser(local=True), workspace=tmp_path)
	await agent.run()
	agent.add_new_task('second')
	await agent.run()
	first, second = sent
	assert (first['tool_calls'], first['follow_up'], first['cells']) == ({'python': 1, 'finish': 1}, False, 1)
	assert (second['tool_calls'], second['follow_up'], second['cells']) == ({'finish': 1}, True, 0)
	assert second['downloads'] == 2 and second['download_exts'] == {'csv': 1, 'pdf': 1}
	assert_absent(second, 'Payroll', 'invoice-77')


async def test_a_step_budget_that_forced_the_delivery_is_max_steps_hit(sent, tmp_path, monkeypatch):
	"""agent-llm F3: max_steps=2 forced the delivery-only turn at request 2, and telemetry said max_steps_hit=False."""

	async def start(self):
		return {}

	async def stop(self, downloads_dir=None):
		return []

	monkeypatch.setattr(Browser, 'start', start)
	monkeypatch.setattr(Browser, 'stop', stop)
	model, _ = script(('python', {'code': 'x = 1'}), ('finish', {'success': False, 'result': 'ran out of steps'}))
	await Agent('t', model, browser=Browser(local=True), workspace=tmp_path).run(max_steps=2)
	model, _ = script(('finish', {'success': True, 'result': 'done'}))
	await Agent('t', model, browser=Browser(local=True), workspace=tmp_path).run(max_steps=10)
	assert [(e['status'], e['max_steps_hit'], e['success']) for e in sent] == [
		('completed', True, False),
		('completed', False, True),
	]


async def test_a_browser_harness_cli_call_from_a_cell_sends_no_telemetry(tmp_path, monkeypatch):
	"""The worker env dropped ANONYMIZED_TELEMETRY, so a `browser-harness` CLI call from a cell sent its piped code and
	output (page text in a real run) as cli_event, opted out or not. Control: the same call outside the REPL sends one."""
	import asyncio
	import os
	import subprocess
	import sys

	events, arrived = [], threading.Event()

	class Capture(BaseHTTPRequestHandler):
		def do_POST(self):
			events.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
			arrived.set()
			self.send_response(200)
			self.end_headers()

		def log_message(self, *args):
			pass

	server = ThreadingHTTPServer(('127.0.0.1', 0), Capture)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	monkeypatch.setenv('BH_POSTHOG_HOST', f'http://127.0.0.1:{server.server_address[1]}')
	monkeypatch.setenv('BH_CONFIG_DIR', str(tmp_path / 'bh-config'))  # never the developer's own telemetry config
	cli = [sys.executable, '-c', 'from browser_harness.run import main; main()']
	repl = Repl(tmp_path / 'ws')
	try:
		for opted_out in (True, False):
			if opted_out:
				monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'false')
			else:
				monkeypatch.delenv('ANONYMIZED_TELEMETRY')
			await repl.close()  # a fresh worker sees this env
			code = f'import subprocess\nsubprocess.run({cli!r}, input="print(\'PRIVATE-CELL-CODE\')", text=True)'
			r = await repl.call('exec', code, 60)
			assert r['error'] is None, r['error']
	finally:
		await repl.close()
		monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'false')
	env = {**os.environ, 'BH_REQUIRE_EXISTING_DAEMON': '1'}
	env.pop('ANONYMIZED_TELEMETRY')
	await asyncio.to_thread(subprocess.run, cli, input="print('CONTROL')", text=True, env=env, capture_output=True)
	await asyncio.to_thread(arrived.wait, 15)
	await asyncio.sleep(1)  # the cells' detached senders started earlier than the control's
	server.shutdown()
	assert [e['properties'].get('task') for e in events] == ["print('CONTROL')"]


# --- v3: what is sent, end to end ---


async def test_v3_event_sent_through_the_real_sender_holds_no_canary(chrome, site, posthog, tmp_path):
	"""Every text the task, the code, a typed value, a secret, a page title, a URL query or fragment, a class or cdp()
	method name the model's code chose and a made-up tool name and its arguments carry is a canary; none may appear anywhere in what reaches PostHog (the gzip body as received). The URL path and the result
	are sent, scrubbed; the errors the cells raised themselves as their class. The v3 fields say what happened."""
	rng = random.Random(7)
	c = SimpleNamespace(
		**{
			k: rand(rng, 12).lower()
			for k in 'task secret typed result error error2 path query frag title var js cdp cls mod tool'.split()
		}
	)
	c.path = slug(rng, 12)
	url = f'{site}/{c.path}?{c.query}=1&t={c.title}#{c.frag}'
	code = (
		f'{c.var} = 1\n'
		f'new_tab({url!r}); wait_for_load()\n'
		'js(\'document.getElementById("f").focus()\')\n'
		f'type_text({c.typed!r}); type_secret("pw")\n'
		'print(page_info())\n'
		f"cdp('Runtime.evaluate', expression={('1 + ' + repr(c.js))!r})\n"
		f'try:\n    cdp({c.cdp!r})\nexcept Exception as e:\n    print(e)'
	)
	model, _ = script(
		('python', {'code': code}),
		('python', {'code': f'class {c.cls}(Exception): pass\nraise {c.cls}({c.error!r})'}),
		('python', {'code': f'import {c.mod}'}),
		(c.tool, {'x': c.error2}),
		('finish', {'success': True, 'result': f'{c.result} {c.task} with {c.secret}'}),
	)
	agent = Agent(
		f'{c.task} with {c.secret}',
		model,
		browser=Browser(cdp_url=chrome['http']),
		sensitive_data={'pw': c.secret},
		workspace=tmp_path / 'ws',
	)
	r = await agent.run()
	assert r.status == 'completed', r.error
	(event,) = posthog.events()
	raw = '\n'.join(posthog.bodies)
	sent = ('path', 'result')  # the URL path and the result are sent
	leaked = [name for name, v in vars(c).items() if v in raw and name not in sent]
	assert not leaked, f'leaked {leaked}'
	assert 'type_text(' not in raw and 'Runtime.evaluate' in raw
	p = event['properties']
	assert p['urls_visited'] == [f'http://127.0.0.1/{c.path}']
	# the cell's own raise and import (importlib drops its frames): the class only, never the text or module it named
	assert p['error_messages'] == ['custom', 'ModuleNotFoundError']
	assert p['final_result'] == f'{c.result} <task>'  # the task, quoted whole (and with its secret redacted)
	assert (event['event'], event['distinct_id'], event['uuid']) == ('agent_event', 'bu-test-device', str(uuid.UUID(p['run_id'])))
	assert (p['schema_version'], p['status'], p['steps'], p['is_internal'], p['$lib']) == (
		4,
		'completed',
		5,
		True,  # conftest: every test event is internal
		'browser-use',
	)
	arrays = {k: v for k, v in p.items() if k.startswith('s_')}
	assert len(arrays) == 21 and {len(v) for v in arrays.values()} == {5}
	assert p['s_kind'] == ['nav', 'compute', 'compute', 'none', 'deliver'], p['s_kind']
	assert p['s_err'] == ['', 'custom', 'ModuleNotFoundError', '', ''] and p['s_tools'][3] == 'invalid'
	assert p['s_host'] == ['127.0.0.1'] * 5 and p['s_helpers'][0].startswith('new_tab,wait_for_load,js,type_text')
	assert p['s_ev'][0] & 128 and p['s_nav'][0] >= 1 and p['s_cells'] == [1, 1, 1, 0, 0]
	assert (p['max_err_streak'], p['streak_err'], p['last_progress_step'], p['wasted_steps']) == (2, 'custom', 5, 0)
	h = p['helper_stats']
	assert h['new_tab'][0] == 1 and h['type_text'][:2] == [1, 0] and h['wait_for_load'][0] == 1
	assert p['cdp_stats']['Runtime.evaluate'][0] >= 1 and p['cdp_stats']['invalid'][:2] == [1, 1]
	assert p['cdp_method_counts'] == {'Runtime.evaluate': 1, 'invalid': 1} and p['invalid_tool_calls'] == 1
	assert p['host_stats']['127.0.0.1'][:2] == [5, 2] and p['imports'] == {'other': 1}
	assert p['ms_total'] >= p['ms_cells'] > 0 and p['ms_cells'] >= p['ms_helpers'] > 0 and p['ms_cdp'] > 0
	assert p['ms_model'] >= 0 and p['ms_other'] >= 0 and p['model_attempts'] == 5 and p['s_ttft_ms'] == [-1] * 5
	assert p['first_nav_step'] == 1 and p['first_nav_ms'] >= 0 and p['first_ok_action_ms'] is not None
	assert 0 < p['tel_bytes'] < 64 * 1024 and p['tel_build_us'] > 0 and p['tel_steps_dropped'] == 0
	assert not list(posthog.config.glob('telemetry/inflight/*')) and not list(posthog.config.glob('telemetry/outbox/*'))


async def test_task_text_passed_as_a_url_and_exception_classes_made_at_runtime_never_reach_posthog(
	chrome, site, posthog, tmp_path
):
	"""Privacy red team: new_tab('https://<task text>/') and cdp('Page.navigate', url=...) with text sent that text as a
	hostname in domains. Exception classes the model's code made with type() or a borrowed __module__ are 'custom'."""
	rng = random.Random(11)
	c = SimpleNamespace(**{k: rand(rng, 10).lower() for k in 'nav1 nav2 nav3 cls1 cls2 cls3 out'.split()})
	code = (
		f"try:\n    new_tab('https://{c.nav1} best flights/')\nexcept Exception: pass\n"
		f"try:\n    cdp('Page.navigate', url='https://{c.nav2} x/')\nexcept Exception: pass\n"
		f"try:\n    goto_url('{c.nav3} words here')\nexcept Exception: pass\n"
		f'new_tab({site!r}); wait_for_load(); print(page_info(), {c.out!r})'
	)
	model, _ = script(
		('python', {'code': code}),
		('python', {'code': f"import json\nraise type({c.cls1!r}, (ValueError,), {{'__module__': 'json'}})('x')"}),
		('python', {'code': f"raise type({c.cls2!r}, (KeyError,), {{}})('y')"}),
		('python', {'code': f"class {c.cls3}(OSError):\n    __module__ = 'builtins'\nraise {c.cls3}()"}),
		('finish', {'success': True, 'result': 'done'}),
	)
	r = await Agent('t', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path / 'ws').run()
	assert r.status == 'completed', r.error
	(event,) = posthog.events()
	raw = '\n'.join(posthog.bodies)
	assert not [k for k, v in vars(c).items() if v in raw], raw
	p = event['properties']
	assert p['domains'] == ['127.0.0.1'] and list(p['host_stats']) == ['127.0.0.1']
	assert p['s_err'] == ['', 'custom', 'custom', 'custom', ''] and p['cell_error_types'] == {'custom': 3}


async def test_telemetry_off_sends_fetches_and_writes_nothing(tmp_path, monkeypatch):
	"""ANONYMIZED_TELEMETRY=false: no network call, no subprocess, no thread, no file (no device_id, inflight marker or
	outbox)."""
	import urllib.request

	import browser_use.telemetry.service as service

	config = tmp_path / 'config'
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'false')
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(config))
	monkeypatch.setattr(service, '_device_id', None)
	instance = service.ProductTelemetry()
	monkeypatch.setattr(service, '_instance', instance)

	def forbidden(*args, **kwargs):
		raise AssertionError(f'called with telemetry off: {args[:1]}')

	monkeypatch.setattr(urllib.request, 'urlopen', forbidden)
	monkeypatch.setattr(subprocess, 'Popen', forbidden)
	no_browser(monkeypatch)
	threads = {t.name for t in threading.enumerate()}
	model, _ = script(('finish', {'success': True, 'result': 'ok'}))
	assert (await Agent('t', model, browser=Browser(local=True), workspace=tmp_path / 'ws').run()).status == 'completed'
	instance._at_exit()
	assert 'browser-use-telemetry' not in {t.name for t in threading.enumerate()} - threads
	assert instance._thread is None and not instance._pending
	assert not [p for p in config.rglob('*') if p.is_file()]


def _telemetry_cli(env: dict, *argv: str) -> dict:
	r = subprocess.run(
		[sys.executable, '-m', 'browser_use.cli', 'telemetry', *argv], env=env, capture_output=True, text=True, timeout=60
	)
	assert r.returncode == 0, r.stderr
	return json.loads(r.stdout)


async def test_browser_use_telemetry_disable_stops_agent_and_mcp_events(posthog, tmp_path, monkeypatch):
	"""Review of 1.0.0: `browser-use telemetry disable` wrote browser-harness's telemetry.json and printed enabled: false,
	but every Agent.run() still sent agent_event and every MCP tool call mcp_server_event: the library only read
	ANONYMIZED_TELEMETRY. Disabled: no event, no thread, no file. `telemetry enable` turns them back on."""
	from mcp import types

	import browser_use.telemetry.service as service
	from browser_use.mcp import cli_mcp

	monkeypatch.setenv('BH_CONFIG_DIR', str(tmp_path / 'bh'))
	for name in ('BH_TELEMETRY', 'BROWSER_HARNESS_TELEMETRY'):
		monkeypatch.delenv(name, raising=False)
	env = {**os.environ, 'BROWSER_USE_CONFIG_DIR': str(tmp_path / 'cli-config')}
	assert _telemetry_cli(env, 'disable')['enabled'] is False
	status = _telemetry_cli(env, 'status')
	assert (status['enabled'], status['disabled_by_config'], status['install_id']) == (False, True, None)

	monkeypatch.setattr(service, '_harness_config_disabled', None)  # this process reads the file as a new one would
	no_browser(monkeypatch)
	model, _ = script(('finish', {'success': True, 'result': 'ok'}))
	assert (await Agent('t', model, browser=Browser(local=True), workspace=tmp_path / 'ws').run()).status == 'completed'
	mcp = cli_mcp.CLIMCPServer()
	mcp._ensure_daemon = lambda code: None  # the cell needs no browser
	handler = mcp.server._request_handlers['tools/call'].handler
	call = types.CallToolRequestParams(name='browser_exec', arguments={'code': 'raise KeyError(1)'})
	await handler(None, call)  # pyright: ignore[reportArgumentType]
	assert posthog.telemetry._thread is None and not posthog.telemetry._pending and not posthog.state.attempts
	assert not [p for p in posthog.config.rglob('*') if p.is_file()]

	status = _telemetry_cli(env, 'enable')
	assert (status['enabled'], status['disabled_by_config'], status['install_id']) == (True, False, 'bu-test-device')
	monkeypatch.setattr(service, '_harness_config_disabled', None)
	await handler(None, call)  # pyright: ignore[reportArgumentType]
	(event,) = posthog.events()
	assert (event['event'], event['properties']['error_type']) == ('mcp_server_event', 'KeyError')


@pytest.mark.parametrize(
	'name, value', [('ANONYMIZED_TELEMETRY', 'n'), ('ANONYMIZED_TELEMETRY', 'disable'), ('BH_TELEMETRY', '0')]
)
def test_telemetry_status_reports_what_browser_use_sends(tmp_path, monkeypatch, name, value):
	"""Review of 1.0.0: ANONYMIZED_TELEMETRY=n or =disable turned the library off, but `browser-use telemetry status`
	printed enabled: true (browser-harness alone only knows 0, false, no and off). And BH_TELEMETRY=0, which status
	showed as off, left agent_event on. Status and every event now agree."""
	import browser_use.telemetry.service as service

	for var in ('BH_TELEMETRY', 'BROWSER_HARNESS_TELEMETRY'):
		monkeypatch.delenv(var, raising=False)
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'true')
	monkeypatch.setenv(name, value)
	monkeypatch.setenv('BH_CONFIG_DIR', str(tmp_path / 'bh'))
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path / 'bu'))
	status = _telemetry_cli(dict(os.environ), 'status')
	assert (status['enabled'], status['disabled_by_env'], status['install_id']) == (False, True, None)
	assert service.ProductTelemetry().enabled is False
	assert not [p for p in tmp_path.rglob('*') if p.is_file()]


def test_a_device_id_that_cannot_be_stored_is_random_per_process(tmp_path, monkeypatch):
	"""Review of 1.0.0: with no writable config dir the device id was a hash of the MAC address and hostname: the same
	for every user, venv and reinstall on the machine, and not removed by deleting browser-use's files."""
	import browser_use.telemetry.service as service

	(tmp_path / 'file').write_text('')
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path / 'file' / 'config'))  # under a file: never created
	monkeypatch.delenv('BROWSER_USE_DEVICE_ID', raising=False)
	monkeypatch.setattr(uuid, 'getnode', lambda: 0x00163E5A7B9C)  # a real (unicast) MAC address
	ids = set()
	for _ in range(2):
		monkeypatch.setattr(service, '_device_id', None)  # a new process
		first = service.get_or_create_device_id()
		assert service.get_or_create_device_id() == first  # one id for the whole process
		ids.add(first)
	assert len(ids) == 2 and all(re.fullmatch(r'[0-9a-f]{32}', i) for i in ids), ids


# --- v4: URLs, error messages and the final result ---


async def test_planted_secrets_and_credentials_never_reach_posthog(chrome, site, posthog, tmp_path):
	"""The URL path, error messages and the final result are sent. A sensitive_data value, an API key, a bearer token,
	a password=, a JWT, an email, a query string, the task and typed text planted in them are replaced or dropped
	before they leave the machine: any planted value anywhere in the body as received fails."""
	rng = random.Random(13)
	p = SimpleNamespace(
		secret=rand(rng, 14),
		openai='sk-proj-' + rand(rng, 24),
		anthropic='sk-ant-api03-' + rand(rng, 24),
		google='AIza' + rand(rng, 30),
		bu='bu_' + rand(rng, 24),
		bearer=rand(rng, 20) + '7',
		password=rand(rng, 12),
		email=rand(rng, 8) + '@zqmail.example',
		jwt='eyJ' + rand(rng, 16) + '.' + rand(rng, 16) + '.' + rand(rng, 16),
		path_email=rand(rng, 8) + '@zqpath.example',
		query=rand(rng, 12),
		frag=rand(rng, 12),
		task=rand(rng, 12),
		typed=rand(rng, 12),
	)
	creds = f'{p.openai} {p.anthropic} {p.google} {p.bu} Authorization: Bearer {p.bearer} password={p.password} {p.email}'
	url = f'{site}/{p.path_email}/{p.secret}/{p.bu}?key={p.query}#{p.frag}'
	task = f'find {p.task}'
	model, _ = script(
		('python', {'code': f'new_tab({url!r}); wait_for_load(); type_text({p.typed!r}); print(page_info())'}),
		('python', {'code': lib_raise(f'ValueError({f"auth failed: {creds} {p.jwt} {p.secret}"!r})')}),
		('finish', {'success': True, 'result': f'{task}: {creds} {p.secret}'}),
	)
	agent = Agent(
		task, model, browser=Browser(cdp_url=chrome['http']), sensitive_data={'pw': p.secret}, workspace=tmp_path / 'ws'
	)
	assert (await agent.run()).status == 'completed'
	(event,) = posthog.events()
	raw = '\n'.join(posthog.bodies)
	leaked = [name for name, v in vars(p).items() if v in raw]
	assert not leaked, f'leaked {leaked}: {raw}'
	props = event['properties']
	cred = '<credential> <credential> <credential> <credential> Authorization: Bearer <credential> password=<credential>'
	assert props['urls_visited'] == ['http://127.0.0.1/<email>/<secret:pw>/<token>']  # a key in a path is a path token
	assert props['error_messages'] == [f'ValueError: auth failed: {cred} <email> <credential> <secret:pw>']
	assert props['final_result'] == f'<task>: {cred} <email> <secret:pw>'


async def test_typed_text_and_quoted_task_words_are_never_sent_also_after_a_follow_up(chrome, site, sent, tmp_path):
	"""The task was replaced only when quoted whole, and text the agent typed not at all: an error message or a result
	that quoted part of the task, or what was typed into a page, reached PostHog."""
	rng = random.Random(7)
	words = [rand(rng, 6) for _ in range(8)]
	typed, filled, follow_up = rand(rng, 10), rand(rng, 10), rand(rng, 12)
	code = (
		f'new_tab({site + "/"!r}); wait_for_load()\n'
		'js(\'document.getElementById("f").focus()\')\n'
		f'type_text({typed!r}); fill_input("#f", {filled!r})\n' + lib_raise(f'ValueError("the field rejected " + {typed!r})')
	)
	model, _ = script(
		('python', {'code': code}),
		('finish', {'success': True, 'result': f'Done {" ".join(words[1:7])}: typed {typed} and {filled}'}),
		('finish', {'success': True, 'result': f'again {" ".join(words[:6])}'}),  # the follow-up quotes the first task
	)
	agent = Agent(' '.join(words), model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path)
	assert (await agent.run()).status == 'completed'
	agent.add_new_task(f'and now {follow_up}')
	assert (await agent.run()).status == 'completed'
	first, second = sent
	for props in sent:
		assert_absent(props, typed, filled, *(' '.join(words[i : i + 5]) for i in range(4)))
	assert first['error_messages'] == ['ValueError: the field rejected <typed>']
	assert first['final_result'] == 'Done <task> typed <typed> and <typed>'  # the run takes its last word's colon
	assert second['final_result'] == 'again <task>'


async def test_urls_errors_and_the_result_are_cut_and_capped(sent, tmp_path, monkeypatch):
	"""urls_visited: 50 at most, 200 characters each, without the query; error_messages: 20 at most, 300 characters
	each (the class counters still count every failed cell); final_result: 500 characters."""
	no_browser(monkeypatch)
	visit = (  # the worker's own record of a navigation (CellStats.url), as cdp('Page.navigate') makes it
		'import sys\n'
		'for i in range(60):\n'
		"    sys.modules['__main__'].stats.url(f'https://zq{i}.example/' + 'p' * 300 + f'?q={i}', navigation=True)"
	)
	fails = [('python', {'code': lib_raise(f'ValueError("{i} " + "e" * 400)')}) for i in range(25)]
	model, _ = script(('python', {'code': visit}), *fails, ('finish', {'success': True, 'result': 'r' * 1000}))
	assert (await Agent('t', model, browser=Browser(local=True), workspace=tmp_path).run()).status == 'completed'
	(props,) = sent
	assert props['urls_visited'] == [(f'https://zq{i}.example/' + 'p' * 300)[:200] for i in range(50)]
	assert props['error_messages'] == [(f'ValueError: {i} ' + 'e' * 400)[:300] for i in range(20)]
	assert (props['cell_errors'], props['cell_error_types']) == (25, {'ValueError': 25})
	assert props['final_result'] == 'r' * 500


async def test_the_runs_error_comes_first_and_repeated_messages_are_sent_once(sent, tmp_path, monkeypatch):
	no_browser(monkeypatch)
	model, _ = script(*[('python', {'code': lib_raise('KeyError("same")')})] * 3, ('finish', {'success': False, 'result': 'no'}))
	await Agent('t', model, browser=Browser(local=True), workspace=tmp_path).run()
	(props,) = sent
	assert props['error_messages'] == ["KeyError: 'same'"] and props['cell_error_types'] == {'KeyError': 3}
	sent.clear()
	model, _ = script(('python', {'code': 'data = {}\ndata["Zq9 from the page"]'}))  # then the model fails: the run's error
	await Agent('t', model, browser=Browser(local=True), workspace=tmp_path).run()
	(props,) = sent
	assert props['status'] == 'error' and props['error_messages'][1:] == ['KeyError']  # the cell's own lookup: class only
	assert props['error_messages'][0].startswith('AssertionError: unexpected model call 2')


@pytest.mark.parametrize(
	'text, out',
	[
		('Authorization: Bearer example-token-1', 'Authorization: Bearer <credential>'),
		('authorization: bearer abcdefghijklmnopqrst', 'authorization: bearer <credential>'),  # lowercase, no digit
		('curl -H "Authorization: Basic dXNlcjpwYXNzMTIz"', 'curl -H "Authorization: Basic <credential>"'),
		('login?password=hunter2&user=x', 'login?password=<credential>&user=x'),
		('password=Tr0ub4dor&3 next', 'password=<credential> next'),
		('{"api_key": "zz1234", "access_token": \'t0k\'}', '{"api_key": <credential>, "access_token": <credential>}'),
		('client_secret=abc refresh_token: xyz', 'client_secret=<credential> refresh_token: <credential>'),
		('keys sk-proj-abcdefgh12 sk-ant-api03-abcdefgh AIza' + 'x' * 30, 'keys <credential> <credential> <credential>'),
		('bu_abcdef123456 ghp_abcdefgh1234 phc_abcdefgh123', '<credential> <credential> <credential>'),
		('jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig', 'jwt <credential>'),
		('commit 0123456789abcdef0123456789abcdef01234567', 'commit <credential>'),
		('mail Jane.Doe+x@Example.co.uk or jane%40example.com', 'mail <email> or <email>'),
		('ValueError: <secret:pw> was rejected', 'ValueError: <secret:pw> was rejected'),
		("NameError: name 'basic_task' is not defined", "NameError: name 'basic_task' is not defined"),
		('the basic plan; a token expired; disk-usage-report', 'the basic plan; a token expired; disk-usage-report'),
		('net::ERR at https://admin:Pw1@intranet:8080/a?token=x&q=y#f', 'net::ERR at https://<credential>@intranet/a'),
		# the host as urls_visited sends it: no port, a tunnel or preview deploy as its provider
		('Timeout at https://zq-quiet-river.trycloudflare.com:443/admin', 'Timeout at https://*.trycloudflare.com/admin'),
		(
			'see https://myapp-git-zq-branch-acme.vercel.app and https://Shop.Example',
			'see https://*.vercel.app and https://shop.example',
		),
		('done: https://shop.example/home/deals?ref=zq#top', 'done: https://shop.example/home/deals'),
		(
			r"No file '/Users/jane/a.pdf', C:\Users\jane\a, file:///home/jane/x",
			r"No file '/Users/<user>/a.pdf', C:\Users\<user>\a, file:///home/<user>/x",
		),
		('Cookie: sid=abc123; csrftoken=xyz', 'Cookie: <credential>'),
		('aws AKIAIOSFODNN7EXAMPLE', 'aws <credential>'),
		('at http://admin:<secret:pw>@intranet/x?k=<secret:pw>', 'at http://<credential>@intranet/x'),  # redacted first
		(
			"RuntimeError: JavaScript evaluation failed: TypeError: x; expression: fill('zq')",
			'RuntimeError: JavaScript evaluation failed: TypeError: x; expression: <code>',
		),
		# a reset, invite or magic link's path is its credential, as a query string is; a product slug is not
		('https://app.example.com/reset-password/a3f9b2c1d4e5f6a7', 'https://app.example.com/reset-password/<token>'),
		('https://a.example/invite/3f2a9c1e-8b7d-4e6f-9a0b-1c2d3e4f5a6b', 'https://a.example/invite/<token>'),
		('https://slack.com/magic-link/8XqZ4Kp9LmN2vB7wR3tY6uA1', 'https://slack.com/magic-link/<token>'),
		(
			'https://docs.google.com/d/1BxiMVs0XRA5n-FMdKvBdBZjgmUUqptlbs74OgvE2upms/edit',
			'https://docs.google.com/d/<token>/edit',
		),
		('https://www.apple.com/shop/iphone-15-pro-max-256gb', 'https://www.apple.com/shop/iphone-15-pro-max-256gb'),
		('at https://shop.example/cart;jsessionid=AB12CD34EF56?x=1', 'at https://shop.example/cart'),
		('Failed loading /login?next=/account&sid=abc123def456', 'Failed loading /login'),
		# third-party data an extraction result or a page-quoting error carries
		(
			'John, +1 (415) 555-0137, card 4111 1111 1111 1111, IBAN DE89370400440532013000, SSN 123-45-6789',
			'John, <number>, card <number>, IBAN DE<number>, SSN <number>',
		),
		('Your verification code is 482913', 'Your verification code is <number>'),
		('Timeout 30000ms at http://127.0.0.1:9222/json', 'Timeout 30000ms at http://127.0.0.1/json'),
	],
)
def test_scrub_replaces_credentials_and_emails_and_keeps_ordinary_text(text, out):
	assert scrub(text, [], 300) == out


def test_scrub_redacts_the_runs_secrets_and_the_task_before_it_cuts():
	from browser_use.repl.session import secret_forms

	forms = secret_forms({'pw': 'Zq9 hunter-2'})
	assert scrub('x' * 295 + 'Zq9 hunter-2', forms, 300) == 'x' * 295 + '<secr'  # never 'Zq9 h'
	assert scrub('/a/Zq9%20hunter-2/b/Zq9 hunter-2', forms, 300) == '/a/<secret:pw>/b/<secret:pw>'
	assert scrub('I booked: find flights to Paris', [], 300, task='find flights to Paris') == 'I booked: <task>'
	assert scrub('do Zq9 hunter-2 now', forms, 300, task='do Zq9 hunter-2 now') == '<task>'  # as typed
	assert scrub('ok: do <secret:pw> now', forms, 300, task='do Zq9 hunter-2 now') == 'ok: <task>'  # as redacted
	assert scrub('ok', [], 300, task='ok') == 'ok'  # a short task is ordinary text
	assert scrub(None, forms, 300) is None
	big = ('Zq9 hunter-2 jane@zq.example ' * 40_000)[:1_000_000]  # a 1 MB result: a window is scrubbed, not all of it
	started = time.perf_counter()
	assert scrub(big, forms, 500) == ('<secret:pw> <email> ' * 30)[:500]
	assert time.perf_counter() - started < 0.1
	short = '<secret:pw> ' * 3000 + 'end'  # scrubbed shorter than its window: scrubbed whole
	assert scrub(short.replace('<secret:pw>', 'Zq9 hunter-2') + 'x' * 50_000, forms, 300) == short[:300]


@pytest.mark.parametrize(
	'run',
	['a' * 40_000, 'a.' * 20_000, '%' * 40_000, '-' * 40_000, 'http://' + 'a' * 40_000],
	ids=['letters', 'dotted', 'percent', 'dashes', 'url'],  # Windows caps PYTEST_CURRENT_TEST at 32,767 chars
)
def test_scrub_is_linear_in_a_long_run_of_one_kind_of_character(run):
	"""EMAIL started a match at every character of a run and scanned to its end: a 32k run of letters (hex, base64) in
	a result or an error message took 2.5 s in the telemetry thread, holding the GIL."""
	started = time.perf_counter()
	scrub(run, [], 500, task='zq ' * 100)
	assert time.perf_counter() - started < 0.1


def test_scrub_sends_a_credential_from_this_processs_environment_in_any_format_as_credential(monkeypatch):
	monkeypatch.setenv('ZQ_ACME_API_KEY', 'zq.weird+format.key')
	assert scrub('upstream 401 for key zq.weird+format.key', [], 300) == 'upstream 401 for key <credential>'


def test_scrub_sends_five_task_words_in_a_row_and_typed_text_as_placeholders():
	task = 'Log into the Acme portal as alice, then download the March invoice'
	out = scrub('Done: logged in. log into the acme portal as Alice and downloaded it', [], 300, task=task)
	assert out == 'Done: logged in. <task> and downloaded it'
	assert scrub('the Acme portal is up', [], 300, task=task) == 'the Acme portal is up'  # four words: ordinary text
	assert scrub('searched Paris Hilton; Parisian', [], 300, typed=['Paris Hilton', 'Parisian x']) == 'searched <typed>; Parisian'
	assert scrub('searched for cheap flights paris', [], 300, typed=['cheap flights paris\n']) == 'searched for <typed>'
	# a long message the agent wrote: its end (past 4096 characters) or any five words of it in a row
	message = ' '.join(f'zq{i}' for i in range(2000))
	tail = ' '.join(message.split()[-15:])
	assert len(message) > 4096 and scrub(f'sent: {tail}', [], 300, typed=[message]) == 'sent: <typed>'
	assert scrub('sent: zq10 zq11 zq12 zq13 zq14 ok', [], 300, typed=[message]) == 'sent: <typed> ok'
	# sites put the query in the path: Zillow, Maps, Wikipedia
	for url, typed, out in (
		('https://www.zillow.com/homes/123-Main-St-Springfield-IL_rb/', '123 Main St, Springfield, IL', '/homes/<typed>_rb/'),
		('https://www.google.com/maps/search/pizza+near+me/', 'pizza near me', '/maps/search/<typed>/'),
		('https://en.wikipedia.org/wiki/Albert_Einstein', 'Albert Einstein', '/wiki/<typed>'),
		('https://www.airbnb.com/s/Lisbon%20Portugal/homes', 'Lisbon Portugal', '/s/<typed>/homes'),
	):
		assert scrub(url, [], 200, typed=[typed]).endswith(out), url


@pytest.mark.parametrize(
	'url, out',
	[
		('https://user:pw@Shop.Example.com:8443/cart/42?token=abc#x', 'https://shop.example.com/cart/42'),
		('http://127.0.0.1:9222/json/version?x=1', 'http://127.0.0.1/json/version'),
		('http://[::1]:9222/json', 'http://[::1]/json'),
		('https://example.com', 'https://example.com/'),
		('https://example.com/a/./b/../c#top', 'https://example.com/a/c'),
		('https://zq-quiet-river.trycloudflare.com/admin?k=1', 'https://*.trycloudflare.com/admin'),
		('https://shop.example/cart;jsessionid=AB12CD?x=1', 'https://shop.example/cart'),
		('about:blank', None),
		('file:///Users/jane/secret.pdf', None),
		('data:text/html,<p>hi</p>', None),
		('chrome://settings', None),
		('https://zq best flights for jane doe/', None),
	],
)
def test_page_url_keeps_scheme_host_and_path_only(url, out):
	assert page_url(url) == out


def test_text_typed_one_key_at_a_time_is_one_typed_text():
	"""press_key('h'), press_key('i') or the agent's own cdp('Input.dispatchKeyEvent', type='char', text='h') typed
	text that scrub never knew: each key alone is shorter than MIN_TYPED, so an error or result quoting it sent it."""
	from browser_use.repl import worker

	press = worker._counted('press_key', lambda key, modifiers=0: None)
	click = worker._counted('click_at_xy', lambda x, y: None)
	worker.stats.take()
	for c in 'alice smith':
		press(c)
	press('Tab')
	for c in 'Zq9pass':
		press(c)
	press('a', modifiers=2)  # Ctrl+A selects, types nothing
	for c in 'acme':
		press(c)
	click(1, 2)
	for c in 'Paris':  # key events the agent sent itself
		worker.stats.record_key(c)
	assert worker.stats.take()['typed'] == ['alice smith', 'Zq9pass', 'acme', 'Paris']
	assert scrub('ValueError: no user alice smith', [], 300, typed=['alice smith']) == 'ValueError: no user <typed>'


def test_cell_stats_list_each_url_once_in_order_after_the_agent_navigated():
	"""A page read lists its URL only in a tab the agent navigated: Browser('chrome') reaches the user's other tabs
	(their mail), whose hostname alone counts."""
	from browser_use.repl.worker import CellStats

	s = CellStats()
	s.url('https://mail.example.com/inbox/42', tab='T1')  # the user's own tab, before the agent navigated
	s.url('https://shop.example.com/a?x=1', navigation=True, tab='T1')
	s.url('https://shop.example.com/a?x=2#f', tab='T1')  # the same page with another query
	s.url('https://pay.example.com/checkout', tab='T1')  # a link the agent clicked there
	s.url('https://mail.example.com/mail/u/0/zq-thread', tab='T2')  # switch_tab() to the user's mail: its host only
	s.url('https://docs.example.com/d/zq-doc')  # no tab known
	out = s.take()
	assert out['urls'] == ['https://shop.example.com/a', 'https://pay.example.com/checkout']
	assert out['hosts'] == ['docs.example.com', 'mail.example.com', 'pay.example.com', 'shop.example.com']
	s.url('https://shop.example.com/a', navigation=True)  # a revisit in a later cell
	assert s.take()['urls'] == []
	stats = RunStats()
	for urls in (['https://a.example/1', 'https://a.example/2'], ['https://a.example/2', 'https://a.example/3']):
		stats.add_cell({'stats': {'urls': urls}}, '', 0.1)  # a restarted worker reports a URL again
	assert stats.urls == ['https://a.example/1', 'https://a.example/2', 'https://a.example/3']


# --- performance ---


def test_recording_hooks_cost_microseconds():
	"""Contract: under 20 us per recorded event (p50 of 20 batches). Real numbers are printed for the PR."""
	from pydantic_ai.messages import ModelResponse, ToolCallPart
	from pydantic_ai.usage import RequestUsage

	from browser_use.repl.worker import CellStats
	from browser_use.telemetry.recorder import RunRecorder

	rec = RunRecorder()
	response = ModelResponse(
		parts=[ToolCallPart('python', {'code': 'x'}), ToolCallPart('python', {'code': 'y'})],
		usage=RequestUsage(input_tokens=1000, output_tokens=50, details={'reasoning_tokens': 10}),
		finish_reason='tool_call',
	)
	ms = 1_000_000
	cell = {
		'output': 'x' * 500,
		'images': [],
		'error': None,
		'stats': {
			'helper_t': {'goto_url': [1, 0, 50 * ms, 50 * ms], 'wait_for_load': [1, 0, 300 * ms, 300 * ms], 'js': [2, 0, ms, ms]},
			'cdp_t': {'Page.navigate': [1, 0, 40 * ms, 40 * ms], 'Runtime.evaluate': [3, 0, 3 * ms, ms]},
			'events': {},
			'navigations': 1,
			'host': 'example.com',
			'new_pages': 1,
		},
	}
	stats = CellStats()

	def per_call(fn, n=5000) -> float:
		batches = []
		for _ in range(20):
			t = time.perf_counter_ns()
			for _ in range(n):
				fn()
			batches.append((time.perf_counter_ns() - t) / n / 1000)
		return statistics.median(batches)

	def model_step():
		rec.attempt_start()
		rec.attempt_ok(response, False)

	results = {
		'attempt_start+attempt_ok': per_call(model_step),
		'cell': per_call(lambda: rec.cell(cell, 'x = 1', 5 * ms)),
		'retry': per_call(lambda: rec.retry('tool_args')),
		'phase': per_call(lambda: rec.phase('preflight', 1000)),
		'worker CellStats.timed': per_call(lambda: stats.timed('cdp_t', 'Runtime.evaluate', 1000, False)),
	}
	print('\nrecording cost, us per call (p50 of 20 batches):', {k: round(v, 2) for k, v in results.items()})
	assert max(results.values()) < 20, results


def test_a_1000_step_run_builds_under_50_ms_and_fits_64_kb():
	"""Build runs in the telemetry thread, but it must stay cheap at exit too: 1000 steps, 50 helpers, 50 CDP methods
	and 30 hosts build in well under 50 ms and the sent event fits 64 KB (steps capped at 200)."""
	import browser_use.telemetry.service as service
	from browser_use.telemetry.recorder import RunRecorder, Step
	from browser_use.telemetry.stats import RunStats
	from browser_use.telemetry.views import AgentTelemetryEvent

	rec = RunRecorder()
	for i in range(1000):
		s = Step(i * 1000, 900, 300)
		s.inp, s.out, s.cells, s.cell_ms, s.nav = 50_000 + i * 100, 200, 1, 80, i % 3 == 0
		s.tools, s.helpers, s.host, s.err = (
			['python'],
			['goto_url', 'js', 'wait_for_load'],
			f'h{i % 30}.example.com',
			'ValueError' if i % 7 == 0 else '',
		)
		s.code = i % 5
		rec.steps.append(s)
	stats = RunStats()
	stats.helper_t = {f'helper_{i}': [10, 1, 10**8, 10**7] for i in range(60)}
	stats.cdp_t = {'Runtime.evaluate': [100, 2, 10**9, 10**8], **{f'X{i}.y': [1, 0, 1, 1] for i in range(60)}}
	times = []
	for _ in range(50):
		t = time.perf_counter_ns()
		v3 = rec.build(stats, 1_000_000)
		times.append((time.perf_counter_ns() - t) / 1e6)
	event = AgentTelemetryEvent('1', 'pip', **v3)
	job = service.Job('agent_event', lambda steps, keys: {**event.properties, **rec.build(stats, 1_000_000, steps, keys)})
	built = service.ProductTelemetry()._event(job)
	size = len(json.dumps(built['properties'], separators=(',', ':')))
	gz = len(service.ProductTelemetry._body([built]))
	print(f'\nbuild of 1000 steps: p50 {statistics.median(times):.2f} ms; event {size} B, gzipped batch {gz} B')
	assert statistics.median(times) < 50 and size <= 64 * 1024
	assert len(built['properties']['s_t']) == 200 and built['properties']['tel_steps_dropped'] == 800
	assert built['properties']['s_t'][49] == 49_000 and built['properties']['s_t'][50] == 850_000  # first 50, last 150


async def test_run_end_does_not_wait_for_a_dead_posthog(dead_posthog, tmp_path, monkeypatch):
	"""v2 called posthog's flush() in run()'s finally: up to 10 s with PostHog unreachable, plus a 65 ms import. Now the
	end of a run only queues the event: _capture and the run-start marker take well under 50 ms, PostHog dead or not."""
	no_browser(monkeypatch)
	took = {}
	for name in ('_capture', '_telemetry_started'):
		original = getattr(Agent, name)

		def timed(self, *args, original=original, name=name):
			t = time.perf_counter()
			original(self, *args)
			took[name] = max(took.get(name, 0), (time.perf_counter() - t) * 1000)

		monkeypatch.setattr(Agent, name, timed)
	for _ in range(2):  # the first in a process included
		model, _ = script(('python', {'code': 'x = 1'}), ('finish', {'success': True, 'result': 'ok'}))
		t = time.perf_counter()
		r = await Agent('t', model, browser=Browser(local=True), workspace=tmp_path / 'ws').run()
		assert r.status == 'completed'
	print(
		f'\nrun end with a dead PostHog: _capture {took["_capture"]:.2f} ms, run start marker {took["_telemetry_started"]:.2f} ms'
	)
	assert took['_capture'] < 50 and took['_telemetry_started'] < 50, took


EXIT_SCRIPT = """
import atexit, os, sys, time
atexit.register(lambda: print(f'EXIT {(time.perf_counter() - marks[0]) * 1000:.1f}', flush=True))  # runs last
marks = []
import browser_use.telemetry.service as service
service.POSTHOG_HOST = sys.argv[1]
from browser_use.telemetry.views import AgentTelemetryEvent
service.ProductTelemetry._loop = lambda self: None  # only the exit path: the thread racing it is tested apart
t = service.telemetry()
t.capture(AgentTelemetryEvent(version='1', source='pip', model='exit-test', run_id=os.urandom(16).hex()))
atexit.register(lambda: marks.append(time.perf_counter()))  # runs first: before telemetry's own handler
"""


@pytest.mark.parametrize('live', [False, True])
def test_a_one_shot_script_exits_fast_and_its_event_still_arrives(posthog, live, tmp_path):
	"""A script that runs one Agent and exits: telemetry's exit handler hands the queued event to a detached sender
	(< 150 ms), and the event reaches PostHog after the process is gone. With PostHog down it waits in the outbox for
	the next process."""
	import browser_use.telemetry.service as service

	posthog.state.down = not live
	env = {**os.environ, 'ANONYMIZED_TELEMETRY': 'true', 'BROWSER_USE_CONFIG_DIR': str(posthog.config)}
	cmd = [sys.executable, '-c', EXIT_SCRIPT, service.POSTHOG_HOST]
	out = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
	assert 'EXIT' in out.stdout, (out.stdout, out.stderr[-3000:])
	exit_ms = float(re.search(r'EXIT ([\d.]+)', out.stdout)[1])
	print(f'\nexit handler with a queued event: {exit_ms:.1f} ms')
	assert exit_ms < 150, out
	if live:
		(event,) = posthog.events()
		assert event['properties']['model'] == 'exit-test'
		deadline = time.monotonic() + 10
		while list(posthog.config.glob('telemetry/outbox/*')) and time.monotonic() < deadline:
			time.sleep(0.05)
		assert not list(posthog.config.glob('telemetry/outbox/*'))
	else:
		outbox = posthog.config / 'telemetry' / 'outbox'
		deadline = time.monotonic() + 15  # the detached sender tried (the only poster) and put the file back
		while time.monotonic() < deadline and not (posthog.state.attempts and not list(outbox.glob('*.sending'))):
			time.sleep(0.05)
		assert posthog.state.attempts == 1 and len(list(outbox.glob('*.gz'))) == 1, (posthog.state, list(outbox.iterdir()))
		posthog.state.down = False
		posthog.telemetry._send_outbox()  # what the next process's telemetry thread does first
		(event,) = posthog.events()
		assert event['properties']['model'] == 'exit-test' and not list(posthog.config.glob('telemetry/outbox/*'))


FIRST_RUN_SCRIPT = """
import sys
import browser_use.telemetry.service as service
service.POSTHOG_HOST = sys.argv[1]
from browser_use.telemetry.views import AgentTelemetryEvent
service.telemetry().capture(AgentTelemetryEvent(version='1', source='pip', model='first-run'))
"""


def test_a_fresh_installs_first_run_is_sent_under_the_device_id_it_keeps(posthog, monkeypatch):
	"""Release smoke 11-09: a new user's first `Agent(...).run_sync()` arrived in PostHog under a device id that was
	never stored. The telemetry thread and the exit handler built the event at once, each made its own id, and the file
	kept the other: the first run of every install was an orphan, not the start of the user's history."""
	import browser_use.telemetry.service as service

	monkeypatch.delenv('BROWSER_USE_DEVICE_ID')
	for i in range(3):
		config = posthog.config.parent / f'fresh{i}'
		posthog.bodies.clear()
		env = {**os.environ, 'ANONYMIZED_TELEMETRY': 'true', 'BROWSER_USE_CONFIG_DIR': str(config)}
		cmd = [sys.executable, '-c', FIRST_RUN_SCRIPT, service.POSTHOG_HOST]
		subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60, check=True)
		posthog.events()
		deadline = time.monotonic() + 10  # the detached exit sender, if it got the event, is done when the outbox is empty
		while list(config.glob('telemetry/outbox/*')) and time.monotonic() < deadline:
			time.sleep(0.05)
		ids = {e['distinct_id'] for b in list(posthog.bodies) for e in json.loads(b)['batch']}
		assert ids == {(config / 'device_id').read_text()}, (i, ids)


def test_one_device_id_per_machine_when_two_callers_create_it_at_once(tmp_path, monkeypatch):
	"""Two callers in one process (the telemetry thread, the exit handler) and two processes (parallel first runs) that
	find no device_id file each made an id: the first caller's file write is the id every caller returns."""
	import uuid_extensions

	import browser_use.telemetry.service as service

	monkeypatch.delenv('BROWSER_USE_DEVICE_ID', raising=False)
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))
	monkeypatch.setattr(service, '_device_id', None)
	got = {}
	made = iter(['id-a', 'id-b'])

	def other_caller_while_this_one_makes_its_id():
		if 'exit' not in got:  # the first caller: the second starts now and gets as far as it can
			other = threading.Thread(target=lambda: got.update(exit=service.get_or_create_device_id()))
			got['exit'] = None
			other.start()
			other.join(0.5)  # it either finished (no lock: its own id) or waits for this caller
			got['other'] = other
		return next(made)

	monkeypatch.setattr(uuid_extensions, 'uuid7str', other_caller_while_this_one_makes_its_id)
	got['thread'] = service.get_or_create_device_id()
	got['other'].join(5)
	assert got['thread'] == got['exit'] == (tmp_path / 'device_id').read_text(), got

	# another process wrote the file after this one looked and before it wrote: the file's id wins
	(tmp_path / 'device_id').unlink()
	monkeypatch.setattr(service, '_device_id', None)

	def another_process_writes_first():
		(tmp_path / 'device_id').write_text('id-other-process')
		return 'id-this-process'

	monkeypatch.setattr(uuid_extensions, 'uuid7str', another_process_writes_first)
	assert service.get_or_create_device_id() == 'id-other-process' == (tmp_path / 'device_id').read_text()
	assert not list(tmp_path.glob('*.tmp'))


def test_an_outbox_file_a_dead_sender_claimed_is_sent_and_one_this_process_still_owns_is_not(posthog):
	"""CI (ubuntu, windows): a one-shot script's telemetry thread, starting while the exit handler wrote the outbox, claimed
	the file (<run_id>.<pid>.sending) and died at exit mid-send; the detached sender found nothing, and nothing ever sent
	a .sending file again: the event was lost. Now a dead sender's claim goes back to the box, a live one's is left, and
	the thread leaves the files of this process's own queued events to the exit sender."""
	from browser_use.telemetry.service import Job

	dead = subprocess.Popen([sys.executable, '-c', 'pass'])
	dead.wait()
	box = posthog.config / 'telemetry' / 'outbox'
	box.mkdir(parents=True)
	t = posthog.telemetry
	body = lambda model: t._body([t._event(Job('agent_event', lambda s, k: {'model': model}))])  # noqa: E731
	(box / f'{uuid.uuid4().hex}.{dead.pid}.sending').write_bytes(body('stranded'))
	live = box / f'{uuid.uuid4().hex}.{os.getppid()}.sending'  # a sender still running: its send, not ours
	live.write_bytes(body('in-flight'))
	own = Job('agent_event', lambda s, k: {'model': 'own'})
	t._pending[own.run_id] = own
	(box / f'{own.run_id}.gz').write_bytes(body('own'))
	t._send_outbox()
	assert [e['properties']['model'] for e in posthog.events()] == ['stranded']
	assert sorted(p.name for p in box.iterdir()) == sorted([live.name, f'{own.run_id}.gz'])


def test_a_one_shot_process_sends_the_outbox_it_finds_and_a_full_outbox_keeps_its_event(posthog):
	"""RC test 11-09 (cli-3): only the telemetry thread sent the outbox, and a CLI call exits before its thread gets
	there. Once 20 files had piled up (offline), every later CLI event was dropped even online, and nothing was ever sent
	or expired. Now the exit sender takes the outbox along: a dead sender's claim is back, a file past 7 days is
	deleted, a full outbox drops its oldest file instead of the new event, and the rest arrives."""
	import browser_use.telemetry.service as service
	from browser_use.telemetry.service import Job

	dead = subprocess.Popen([sys.executable, '-c', 'pass'])
	dead.wait()
	box = posthog.config / 'telemetry' / 'outbox'
	box.mkdir(parents=True)
	t = posthog.telemetry
	now = time.time()

	def put(model: str, age_s: float, name: str = '') -> None:
		path = box / (name or f'{uuid.uuid4().hex}.gz')
		path.write_bytes(t._body([t._event(Job('agent_event', lambda s, k: {'model': model}))]))
		os.utime(path, (now - age_s, now - age_s))

	for i in range(18):
		put(f'old{i}', 3600 + i)
	put('evicted', 6 * 86400)  # the oldest left once the outbox is full
	put('expired', 8 * 86400)
	put('stranded', 86400, f'{uuid.uuid4().hex}.{dead.pid}.sending')
	env = {**os.environ, 'ANONYMIZED_TELEMETRY': 'true', 'BROWSER_USE_CONFIG_DIR': str(posthog.config)}
	out = subprocess.run([sys.executable, '-c', EXIT_SCRIPT, service.POSTHOG_HOST], env=env, capture_output=True, timeout=60)
	assert b'EXIT' in out.stdout, (out.stdout, out.stderr[-3000:])
	models = [e['properties']['model'] for e in posthog.events(20)]
	deadline = time.monotonic() + 10
	while list(box.iterdir()) and time.monotonic() < deadline:
		time.sleep(0.05)
	assert sorted(models) == sorted(['exit-test', 'stranded', *(f'old{i}' for i in range(18))]), models
	assert not list(box.iterdir())


def test_once_the_process_exits_its_thread_claims_no_outbox_file_or_crash_report(posthog, monkeypatch):
	"""RC test 11-09, Linux: a CLI call's thread reached the outbox while the exit handler ran, claimed the oldest file
	and froze mid-send with the process; the next call put it back and its thread claimed it again: never sent. Nor does
	it send the event the exit handler took: its TLS setup ran in OpenSSL while the exit freed OpenSSL, a segfault in 2-4%
	of online CLI calls on macOS, and the event went out twice."""
	import browser_use.telemetry.service as service
	from browser_use.telemetry.service import Job

	dead = subprocess.Popen([sys.executable, '-c', 'pass'])
	dead.wait()
	spawned = []
	monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: spawned.append(a))  # the exit sender
	t = posthog.telemetry
	box, inflight = posthog.config / 'telemetry' / 'outbox', posthog.config / 'telemetry' / 'inflight'
	box.mkdir(parents=True)
	inflight.mkdir(parents=True)
	(box / f'{uuid.uuid4().hex}.gz').write_bytes(t._body([t._event(Job('agent_event', lambda s, k: {'model': 'old'}))]))
	marker = {'pid': dead.pid, 'started': time.time() - 60, 'steps': 1, 'props': {'model': 'crashed'}}
	(inflight / f'{uuid.uuid4().hex}.json').write_text(json.dumps(marker))
	own = Job('agent_event', lambda s, k: {'model': 'own'})
	t._pending[own.run_id] = own
	t._at_exit()
	before = sorted(p.name for p in posthog.config.rglob('*'))
	t._send_outbox()  # what the thread does next, while the interpreter finalizes
	t._send_crashed()
	t._send(own)
	assert len(spawned) == 1 and posthog.state.attempts == 0
	assert sorted(p.name for p in posthog.config.rglob('*')) == before


def test_a_send_that_fails_goes_to_the_outbox_and_is_counted(posthog, monkeypatch):
	import browser_use.telemetry.service as service
	from browser_use.telemetry.views import AgentTelemetryEvent

	live = service.POSTHOG_HOST
	monkeypatch.setattr(service, 'POSTHOG_HOST', 'http://127.0.0.1:9')
	t = posthog.telemetry
	t.capture(AgentTelemetryEvent(version='1', source='pip', model='first'))
	assert t.flush(10)
	assert t.send_failures == 1 and len(list(posthog.config.glob('telemetry/outbox/*.gz'))) == 1
	monkeypatch.setattr(service, 'POSTHOG_HOST', live)
	t._send_outbox()
	assert [e['properties']['model'] for e in posthog.events()] == ['first']


def test_a_run_whose_process_died_is_sent_as_crashed(posthog):
	"""A marker written while a run was in progress, by a process that no longer exists, is sent once as status
	crashed with the step count the marker last had."""
	from browser_use.telemetry.views import AgentTelemetryEvent

	dead = subprocess.Popen([sys.executable, '-c', 'pass'])
	dead.wait()
	run_id = uuid.uuid4().hex
	marker = posthog.config / 'telemetry' / 'inflight' / f'{run_id}.json'
	marker.parent.mkdir(parents=True)
	props = AgentTelemetryEvent(version='1', source='pip', model='m', run_id=run_id, timeout_s=1700).properties
	started = time.time() - 120
	marker.write_text(json.dumps({'pid': dead.pid, 'started': started, 'updated': started + 90, 'steps': 7, 'props': props}))
	alive = posthog.config / 'telemetry' / 'inflight' / 'alive.json'  # a run of a process still running: left alone
	alive.write_text(json.dumps({'pid': os.getppid(), 'started': time.time(), 'props': props}))
	posthog.telemetry._send_crashed()
	(event,) = posthog.events()
	p = event['properties']
	assert (p['status'], p['steps'], p['ms_total'], event['uuid']) == ('crashed', 7, 90_000, str(uuid.UUID(run_id)))
	assert not marker.exists() and alive.exists()


async def test_a_run_in_progress_has_a_marker_that_goes_away_when_its_event_is_sent(posthog, tmp_path, monkeypatch):
	"""The crash marker exists while the run does (the thread writes it), holds no task text, and is gone once the
	run's event is sent."""
	from pydantic_ai.messages import ModelResponse, ToolCallPart
	from pydantic_ai.models.function import FunctionModel

	no_browser(monkeypatch)
	markers = []

	def slow(messages, info):
		time.sleep(0.5)  # the telemetry thread writes the marker meanwhile
		markers.extend(p.read_text() for p in posthog.config.glob('telemetry/inflight/*.json'))
		return ModelResponse(parts=[ToolCallPart('finish', {'success': True, 'result': 'ok'})])

	await Agent('Zq-marker-task-text', FunctionModel(slow), browser=Browser(local=True), workspace=tmp_path / 'ws').run()
	(event,) = posthog.events()
	assert posthog.telemetry.flush(5)
	(marker,) = markers
	assert 'Zq-marker-task-text' not in marker and json.loads(marker)['props']['run_id'] == event['properties']['run_id']
	assert not list(posthog.config.glob('telemetry/inflight/*'))


# --- what the recorder derives ---


def test_struggle_metrics_and_step_kinds():
	from browser_use.telemetry.recorder import EV_NEW_PAGE, RunRecorder, Step
	from browser_use.telemetry.stats import RunStats

	def step(err='', helpers=(), nav=0, host='a.com', ev=0, code=None, tools=('python',)):
		s = Step(0, 1, -1)
		s.err, s.helpers, s.nav, s.host, s.ev, s.code, s.tools, s.cells = err, list(helpers), nav, host, ev, code, list(tools), 1
		return s

	rec = RunRecorder()
	rec.steps = [
		step(helpers=['goto_url'], nav=1, ev=EV_NEW_PAGE, code=1),
		step('TimeoutError', ['click_at_xy'], code=2),
		step('TimeoutError', ['click_at_xy'], code=2),
		step('TimeoutError', ['click_at_xy'], code=3),
		step(helpers=['wait_for_load'], code=4),
		step(helpers=['js'], code=5),
		step(code=6),
		step(tools=('finish',), helpers=[]),
	]
	out = rec.build(RunStats(), 1000)
	assert out['s_kind'] == ['nav', 'interact', 'interact', 'interact', 'wait', 'read', 'compute', 'deliver']
	assert (out['max_err_streak'], out['err_streaks_3'], out['streak_err'], out['streak_kind'], out['streak_helper']) == (
		3,
		1,
		'TimeoutError',
		'interact',
		'click_at_xy',
	)
	assert (out['repeat_fail_steps'], out['repeat_code_steps'], out['last_progress_step'], out['wasted_steps']) == (2, 1, 8, 0)
	assert out['max_host_streak'] == 8 and out['s_ev'][2] & 256 and out['host_stats'] == {'a.com': [8, 3, 0, 0, 0, 1, 0]}


def test_model_names_and_provider_codes_never_carry_free_text():
	from browser_use.telemetry.recorder import RunRecorder, _code

	assert _code('rate_limit_exceeded') == 'rate_limit_exceeded' and _code(429) == '429'
	assert _code('Your key sk-123 was rejected') == 'other' and _code(None) == ''
	rec = RunRecorder(model='openai:gpt-6-luna')
	assert rec._model_name('gpt-6-luna-2026-10-01') == 'gpt-6-luna-2026-10-01'
	assert rec._model_name('/home/jane/models/acme-payroll.gguf') == 'other'
	assert rec._model_name('llama-3-70b') == 'other'  # a different model than configured: a custom endpoint's text
	assert RunRecorder(model='bu-auto', gateway=True)._model_name('claude-opus-5') == 'claude-opus-5'


async def test_delivery_repairs_and_retries_are_counted_at_their_raise_sites(sent, tmp_path, monkeypatch):
	no_browser(monkeypatch)
	model, _ = script(
		('finish', {'success': True, 'result': '...'}),  # a placeholder: one repair
		('python', {}),  # missing code: a tool argument retry
		('finish', {'success': True, 'result': 'done'}),
	)
	await Agent('t', model, browser=Browser(local=True), workspace=tmp_path).run()
	(p,) = sent
	assert p['retries'] == {'delivery_placeholder': 1, 'tool_args': 1} and p['delivery_repairs'] == 1, p
	assert p['retry_prompts'] == 2 and p['status'] == 'completed' and p['error_phase'] is None


async def test_why_a_run_ended(sent, tmp_path, monkeypatch):
	"""error_phase: where a failed run stopped; budget for a run its limits ended."""
	no_browser(monkeypatch)
	model, _ = script(('python', {'code': 'x = 1'}), ('python', {'code': 'x = 2'}))
	await Agent('t', model, browser=Browser(local=True), workspace=tmp_path).run(max_steps=1)
	monkeypatch.setattr('browser_use.agent.service.provider_preflight', lambda model: 'rejected the API key')
	await Agent('t', script()[0], browser=Browser(local=True), workspace=tmp_path).run()
	assert [(e['status'], e['error_phase']) for e in sent] == [('max_steps', 'budget'), ('error', 'preflight')]
	assert sent[0]['budget_hit'] == 'max_steps' and sent[0]['delivery_turn'] is True and sent[0]['s_ev'][0] & 8
	assert sent[1]['ms_preflight'] >= 0 and sent[1]['steps'] == 0 and sent[1]['s_t'] == []


def test_a_cell_does_not_pay_for_the_installed_package_and_cdp_method_lists():
	"""v2 checked each cell's imports and cdp() methods as it ran: the first cell of a process listed every installed
	distribution and every CDP method (~300 ms on the agent path). The check now runs when the event is built."""
	code = (
		'import time\n'
		'from browser_use.telemetry.stats import RunStats, known_cdp_method, known_module\n'
		't = time.perf_counter()\n'
		"RunStats().add_cell({'stats': {'cdp': {'Page.navigate': 1}}}, 'import pandas\\nimport json', 0.1)\n"
		'print(round((time.perf_counter() - t) * 1000, 2), known_module.cache_info().currsize, known_cdp_method.cache_info().currsize)'
	)
	out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True).stdout.split()
	assert out[1:] == ['0', '0'] and float(out[0]) < 5, out


def test_the_telemetry_thread_does_not_list_every_package_or_cdp_method():
	"""The thread listed every installed distribution and CDP method when it started (~120 ms of CPU, importing all of
	cdp-use). Holding the GIL, that slowed the first run of a process by ~40 ms (a local Chromium run: 2153 -> 2192 ms).
	Names are now checked one at a time: the same answers, without importing cdp-use."""
	code = (
		'import sys, time\n'
		'import browser_use.telemetry.service as s\n'
		'from browser_use.telemetry.stats import known_cdp_method, known_module\n'
		't = time.perf_counter()\n'
		's.telemetry()._warm()\n'
		"names = [known_module(n) for n in ('json', 'PIL', 'pydantic_ai', 'zqnotinstalled', 'os.path')]\n"
		"names += [known_cdp_method(m) for m in ('Page.navigate', 'page.navigate', 'DOM.getBoxModel', 'Page.zq', 'Zq.navigate',"
		" 'BrowserUse.setCaptchaSolverEnabled', '../x.navigate', 'Page.navigate(')]\n"
		"print(round((time.perf_counter() - t) * 1000, 2), 'cdp_use' in sys.modules, names)"
	)
	out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True).stdout
	ms, imported, names = out.split(' ', 2)
	assert imported == 'False' and float(ms) < 60, out
	assert names.strip() == str([True, True, True, False, False, True, False, True, False, False, True, False, False])


def test_cdp_methods_and_modules_allowed_are_the_protocols_and_the_installed_ones():
	"""The per-name checks accept every method cdp-use's clients define and every module of an installed distribution."""
	from importlib.metadata import packages_distributions

	from cdp_use.cdp.library import CDPLibrary

	from browser_use.telemetry.stats import known_cdp_method, known_module

	lib = CDPLibrary(None)  # type: ignore[arg-type]
	methods = {
		f'{d}.{m}'
		for d, c in vars(lib).items()
		if not d.startswith('_')
		for m in dir(c)
		if m[:1].isupper() is False and not m.startswith('_') and callable(getattr(c, m))
	}
	assert len(methods) > 500 and all(known_cdp_method(m) for m in methods)
	# top_level.txt also lists names no import finds (pywin32's adsi lives in win32comext): those are not modules
	importable = [m for m in packages_distributions() if m.isidentifier() and importlib.util.find_spec(m) is not None]
	assert len(importable) > 50 and [m for m in importable if not known_module(m)] == []


def test_no_test_can_send_to_the_real_posthog():
	"""The suite sent a real event per run: a send to a dead host was still retrying when the fixture restored the real
	host. Tests now start from a host where nothing listens, and their events are marked internal."""
	import browser_use.telemetry.service as service

	assert service.POSTHOG_HOST == 'http://127.0.0.1:9' and os.environ['BROWSER_USE_TELEMETRY_INTERNAL'] == '1'


async def test_a_queued_event_does_not_keep_the_runs_messages_alive(dead_posthog, tmp_path, monkeypatch):
	"""The event waits in the sender while PostHog is slow or down (7 s per event unreachable, up to 100 events). Its
	build closure held the run's whole message history, screenshots included, and the thread's loop variable held the
	last one even after it was sent: 1.6 MiB more per 200-step run here, measured with tracemalloc."""
	import gc
	import weakref

	from pydantic_ai.messages import ModelResponse, ToolCallPart
	from pydantic_ai.models.function import FunctionModel

	no_browser(monkeypatch)
	refs = []

	def fn(messages, info):
		done = len(refs) >= 2
		r = ModelResponse(
			parts=[
				ToolCallPart('finish', {'success': True, 'result': 'ok'}) if done else ToolCallPart('python', {'code': 'x = 1'})
			]
		)
		refs.append(weakref.ref(r))
		return r

	r = await Agent('t', FunctionModel(fn), browser=Browser(local=True), workspace=tmp_path / 'ws').run()
	assert r.status == 'completed' and dead_posthog.telemetry._pending
	del r
	gc.collect()
	assert [ref() for ref in refs] == [None, None, None]
	(job,) = dead_posthog.telemetry._pending.values()
	props = job.build(200, 50)
	assert props['tool_calls'] == {'python': 2, 'finish': 1} and props['retry_prompts'] == 0


async def test_a_failed_navigation_counts_on_the_host_that_failed_not_on_chromes_error_page(chrome, sent, tmp_path):
	"""Live run 4 went to an unresolvable host: goto_url returned, no error showed anywhere, and both steps were booked
	on 'chromewebdata', the host of Chrome's error page. The failed navigation now counts, with Chrome's net error code,
	on the host that failed; the URL is the one requested, without its query, never the error page's."""
	model, _ = script(
		('python', {'code': "goto_url('http://zq-nowhere.invalid/zqpath?zq=1'); print(page_info())"}),
		('finish', {'success': False, 'result': 'unreachable'}),
	)
	assert (await Agent('t', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path).run()).status == 'completed'
	(props,) = sent
	assert props['nav_failures'] == 1 and props['nav_errors'] == {'ERR_NAME_NOT_RESOLVED': 1}
	assert 'chromewebdata' not in props['domains'] + props['s_host'] and 'chromewebdata' not in props['host_stats']
	assert props['host_stats']['zq-nowhere.invalid'][5:] == [1, 1] and props['s_ev'][0] & 1024
	assert props['urls_visited'] == ['http://zq-nowhere.invalid/zqpath']
	assert_absent(props, 'zq=1', 'chromewebdata')


def test_a_step_whose_navigation_failed_is_not_progress():
	from browser_use.telemetry.recorder import EV_NAV_FAILED, EV_NEW_PAGE, Step, _struggle

	ok, failed = Step(0, 1, 1), Step(1, 1, 1)
	ok.tools = failed.tools = ['python']
	ok.ev, failed.ev = EV_NEW_PAGE, EV_NEW_PAGE | EV_NAV_FAILED
	assert _struggle([ok, failed])['last_progress_step'] == 1 and _struggle([ok, failed])['wasted_steps'] == 1


def test_a_run_delivered_as_a_text_reply_wastes_no_steps():
	"""Live runs on bu-fast delivered as a plain text reply (finish_via text) in 6 of 11: a 4-step run that read,
	clicked and answered reported wasted_steps 3, because only the finish tool counted as delivering."""
	from browser_use.telemetry.recorder import EV_NEW_PAGE, Step, _struggle

	steps = [Step(i, 1, 1) for i in range(4)]
	for s in steps[:3]:
		s.tools = ['python']
	steps[0].ev = EV_NEW_PAGE  # nav, then read, interact, and a text reply
	assert (_struggle(steps)['last_progress_step'], _struggle(steps)['wasted_steps']) == (4, 0)
	steps[1].tools = []  # a text reply mid-run (sent back for repair) is not the delivery
	assert (_struggle(steps[:3])['last_progress_step'], _struggle(steps[:3])['wasted_steps']) == (1, 2)


def _marked(t, inflight, n: int) -> list:
	ids = [uuid.uuid4().hex for _ in range(n)]
	for run_id in ids:
		t.run_started(run_id, lambda: {'timeout_s': 60}, lambda: {'steps': 0})
	deadline = time.monotonic() + 10
	while len(list(inflight.glob('*.json'))) < n and time.monotonic() < deadline:
		time.sleep(0.02)
	assert len(list(inflight.glob('*.json'))) == n
	return ids


def test_a_run_whose_queued_event_was_dropped_is_not_reported_as_crashed(posthog, monkeypatch):
	"""Past 100 queued events the oldest is dropped. Its run ended: its crash marker goes too, else the next process
	sent it as status crashed (more 'crashes' exactly while PostHog is slow)."""
	import browser_use.telemetry.service as service

	t, inflight = posthog.telemetry, posthog.config / 'telemetry' / 'inflight'
	release = threading.Event()
	real = service.ProductTelemetry._post
	monkeypatch.setattr(
		service.ProductTelemetry, '_post', staticmethod(lambda data, timeout=3.0: release.wait(30) and real(data, timeout))
	)
	ids = _marked(t, inflight, 105)
	for run_id in ids:
		t.capture_run(service.Job('agent_event', lambda steps, keys: {'model': 'm'}, run_id=run_id))
	release.set()
	assert t.flush(60) and t.dropped > 0
	t.stop()
	assert not list(inflight.glob('*.json')) and not t._active


def test_a_run_whose_event_cannot_be_built_is_not_reported_as_crashed(posthog):
	t, inflight = posthog.telemetry, posthog.config / 'telemetry' / 'inflight'
	from browser_use.telemetry.service import Job

	(run_id,) = _marked(t, inflight, 1)

	def broken(steps, keys):
		raise KeyError('a bug in build()')

	t.capture_run(Job('agent_event', broken, run_id=run_id))
	assert t.flush(10)
	t.stop()
	assert not list(inflight.glob('*.json')) and not t._active


def test_a_marker_refresh_that_raises_does_not_end_the_telemetry_thread(posthog, monkeypatch):
	"""The periodic marker refresh ran outside the loop's try: a progress() that raised killed the thread."""
	import browser_use.telemetry.service as service

	monkeypatch.setattr(service, 'MARKER_REFRESH_S', 0.05)
	calls: list[int] = []

	def progress() -> dict:
		calls.append(1)
		raise ValueError('a bug in progress()')

	t = posthog.telemetry
	t.run_started(uuid.uuid4().hex, lambda: {'timeout_s': 60}, progress)
	thread = t._thread
	deadline = time.monotonic() + 10
	while len(calls) < 4 and time.monotonic() < deadline:
		time.sleep(0.02)
	assert thread is not None and thread.is_alive() and len(calls) >= 4


def test_a_crash_report_whose_sender_died_mid_send_is_sent_by_the_next_process(posthog):
	"""_send_crashed claims a marker as <run_id>.<pid>.crashed while it posts; a process killed in that window left the
	claim, and no later process ever sent it or cleaned it up."""
	from browser_use.telemetry.views import AgentTelemetryEvent

	dead = subprocess.Popen([sys.executable, '-c', 'pass'])
	dead.wait()
	run_id = uuid.uuid4().hex
	inflight = posthog.config / 'telemetry' / 'inflight'
	inflight.mkdir(parents=True)
	props = AgentTelemetryEvent(version='1', source='pip', model='m', run_id=run_id, timeout_s=60).properties
	started = time.time() - 3600
	marker = {'pid': dead.pid, 'started': started, 'updated': started + 5, 'steps': 3, 'props': props}
	(inflight / f'{run_id}.{dead.pid}.crashed').write_text(json.dumps(marker))
	posthog.telemetry._send_crashed()
	(event,) = posthog.events()
	assert (event['properties']['status'], event['uuid']) == ('crashed', str(uuid.UUID(run_id)))
	assert not list(inflight.iterdir())


def _in_forked_child(body) -> int:
	"""Run body() in a forked child (a multiprocessing pool on Linux forks so); its exit code: 0 when body() returned
	True."""
	pid = os.fork()
	if pid == 0:  # the child: never back into pytest
		code = 1
		try:
			with warnings.catch_warnings():
				warnings.simplefilter('ignore')
				code = 0 if body() else 1
		finally:
			os._exit(code)
	_, status = os.waitpid(pid, 0)
	return os.waitstatus_to_exitcode(status)


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='fork() is POSIX')
def test_a_forked_childs_first_run_and_first_event_are_not_wiped(posthog):
	"""A child forked after the parent used telemetry reset the inherited state on its first call, after that call had
	registered its run or queued its event: the child's run got no crash marker (a pool worker killed mid-run was never
	reported) and an event sent first was dropped."""
	from browser_use.telemetry.service import Job

	t, inflight = posthog.telemetry, posthog.config / 'telemetry' / 'inflight'
	_marked(t, inflight, 1)  # the parent ran: its thread and pid are what a forked child inherits
	run_id, event_id = uuid.uuid4().hex, uuid.uuid4().hex

	def marks() -> bool:
		t.run_started(run_id, lambda: {'timeout_s': 60}, lambda: {'steps': 0})
		deadline = time.monotonic() + 10
		while not (inflight / f'{run_id}.json').exists() and time.monotonic() < deadline:
			time.sleep(0.02)
		return (inflight / f'{run_id}.json').exists()

	def sends() -> bool:
		t.capture_run(Job('agent_event', lambda steps, keys: {'model': 'm'}, run_id=event_id))
		return t.flush(10)

	assert _in_forked_child(marks) == 0, "the forked child's run got no crash marker"
	assert _in_forked_child(sends) == 0
	assert str(uuid.UUID(event_id)) in {e['uuid'] for e in posthog.events(1)}, "the forked child's first event was dropped"


def test_an_exit_with_no_queued_event_still_hands_the_outbox_to_the_exit_sender(posthog, monkeypatch):
	"""PR 6357 review: the exit handler returned when nothing was queued, so the outbox an earlier process left waited for
	the next process even though this one's thread had started (a run killed before its event was queued)."""
	import browser_use.telemetry.service as service
	from browser_use.telemetry.service import Job

	spawned = []
	monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: spawned.append(a[0]))
	t = posthog.telemetry
	box = posthog.config / 'telemetry' / 'outbox'
	box.mkdir(parents=True)
	old = box / f'{uuid.uuid4().hex}.gz'
	old.write_bytes(t._body([t._event(Job('agent_event', lambda s, k: {'model': 'old'}))]))
	t._at_exit()
	assert len(spawned) == 1 and spawned[0][-1] == str(old)


def test_an_event_the_exit_handler_could_not_write_is_still_written_by_the_thread(posthog, monkeypatch):
	"""PR 6357 review: every queued event counted as handed to the exit sender, also one whose outbox write failed; the
	thread, whose send then failed, skipped its own outbox write and the event was lost."""
	import browser_use.telemetry.service as service
	from browser_use.telemetry.service import Job

	monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: None)
	t = posthog.telemetry
	job = Job('agent_event', lambda s, k: {'model': 'own'})
	t._pending[job.run_id] = job
	write = t._to_outbox
	monkeypatch.setattr(t, '_to_outbox', lambda data, name: None)  # a failed write at exit, also to a temp file
	monkeypatch.setattr(service, '_once_file', lambda data, name: None)
	t._at_exit()
	monkeypatch.setattr(t, '_to_outbox', write)
	t._send(job)  # the thread, mid-send as the process exits
	assert [p.name for p in (posthog.config / 'telemetry' / 'outbox').iterdir()] == [f'{job.run_id}.gz']


def test_a_library_error_quoting_page_text_is_sent_as_its_class_only():
	"""datetime.strptime(text, fmt), urlopen(href), Path(x).read_text() quote their argument: page text. Only errors
	browser-use or browser-harness raised keep their message."""
	from datetime import datetime

	from browser_use.telemetry.stats import raised_by_cell

	page_text = 'Jane Doe owes 4,200 on account'
	try:
		datetime.strptime(page_text, '%Y-%m-%d')
	except ValueError as e:
		assert page_text in str(e) and raised_by_cell(e)
	try:
		exec(compile('raise RuntimeError("no Chrome to attach")', HELPER_FILE, 'exec'))
	except RuntimeError as e:
		assert not raised_by_cell(e)
	try:
		exec(compile('raise ValueError(x)', '<cell 3>', 'exec'), {'x': page_text})
	except ValueError as e:
		assert raised_by_cell(e)


def test_long_typed_texts_are_matched_in_bounded_memory_and_time():
	"""Retest 1.0.1 review: 50 typed texts of 64k characters held every five-word run as a tuple (~600k runs, ~100 MB)
	and compiled a regex per 64k-character form on every scrub (minutes). Every typed text is still matched, the last too."""
	import tracemalloc

	from browser_use.telemetry.stats import _task_grams, scrub

	rng = random.Random(7)
	typed = tuple(' '.join(rng.choice(string.ascii_lowercase) * 6 + str(i) for i in range(9000))[:65536] for _ in range(50))
	_task_grams.cache_clear()
	tracemalloc.start()
	started = time.perf_counter()
	out = scrub('result: ' + typed[-1][30_000:30_400], [], 500, typed=typed)
	_, peak = tracemalloc.get_traced_memory()
	tracemalloc.stop()
	assert '<typed>' in out and len(out) < 40 and time.perf_counter() - started < 10 and peak < 120_000_000  # cut words stay
	assert scrub('İstanbul Kadıköy', [], 500, typed=('İstanbul Kadıköy',)) == '<typed>'


# --- library_feedback: report_issue() mid-run, browser_use.feedback(), `browser-use feedback`, the browser_feedback tool


def _feedback(events: list[dict]) -> list[dict]:
	return [e for e in events if e['event'] == 'library_feedback']


async def test_report_issue_sends_scrubbed_feedback_joined_to_its_run_at_most_three_times(posthog, tmp_path, monkeypatch):
	"""The agent tells the Browser Use team what browser-use got wrong, mid-run: one library_feedback event per call,
	under the device id and run_id of the run's agent_event, scrubbed like its error messages (task, typed text, secrets,
	emails, keys, URL queries, home folders). Three per run; agent_event counts them."""
	no_browser(monkeypatch)
	user_key = 'bu_' + 'Zq9k' * 8
	monkeypatch.setenv('BROWSER_USE_API_KEY', user_key)
	task, secret, typed1, typed2 = 'Zq9 compare the prices of these shoes', 'Zq9-secret-pw', 'Zq9-earlier', 'Zq9-this-cell'
	message = (
		f'type_text lost {typed1} and {typed2} on {task}; pw {secret}; mail jane@zq9.test; see https://zq9.test/a?t=Zq9q '
		f'key sk-ant-Zq9abcdefgh env {user_key} in /Users/Zq9jane/x'
	)
	record = "import sys\nsys.modules['__main__'].stats.record_typed({!r})"  # the worker's own record, as type_text makes it
	model, seen = script(
		('python', {'code': f'{record.format(typed1)}\nraise ValueError("boom")'}),
		('python', {'code': f'{record.format(typed2)}\nprint(report_issue({message!r}))'}),
		('python', {'code': "for i in range(3):\n    print(report_issue(f'again {i}', 'docs'))"}),
		('finish', {'success': True, 'result': 'ok'}),
	)
	agent = Agent(task, model, browser=Browser(local=True), sensitive_data={'pw': secret}, workspace=tmp_path)
	assert (await agent.run()).status == 'completed'
	events = posthog.events(4)
	(run,) = (e for e in events if e['event'] == 'agent_event')
	reports = _feedback(events)
	assert len(reports) == 3 and run['properties']['feedback_count'] == 3
	assert run['properties']['helper_counts']['report_issue'] == 4
	first = reports[0]['properties']
	assert first['message'] == (
		'type_text lost <typed> and <typed> on <task>; pw <secret:pw>; mail <email>; see https://zq9.test/a '
		'key <credential> env <credential> in /Users/<user>/x'
	)
	assert (first['source'], first['category'], first['step'], first['last_error_type']) == ('agent', 'bug', 2, 'ValueError')
	assert first['run_id'] == run['properties']['run_id'] and first['model'] == run['properties']['model']
	assert first['version'] and first['python_version'] and first['os'] and 'browser_harness_version' in first
	assert (first['is_internal'], first['is_ci'] in (True, False), first['schema_version']) == (True, True, 4)
	assert [r['properties']['message'] for r in reports[1:]] == ['again 0', 'again 1']
	assert {r['distinct_id'] for r in events} == {'bu-test-device'}
	assert_absent({'events': events}, 'Zq9', user_key)
	assert not [b for b in posthog.bodies if user_key in b or 'Zq9' in b]  # what went over the wire
	out = str(seen[-1][-1])
	assert out.count('Reported to the Browser Use team') == 2 and 'Already reported 3 issues this run' in out


async def test_with_usage_stats_off_the_agent_and_mcp_report_nothing(posthog, tmp_path, monkeypatch):
	"""The agent's model and an MCP client's model are not the user: ANONYMIZED_TELEMETRY=false means their reports are
	not sent, and they are told so."""
	from mcp import types

	from browser_use.mcp import cli_mcp

	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'false')
	no_browser(monkeypatch)
	model, seen = script(
		('python', {'code': 'print(report_issue("goto_url hangs"))'}), ('finish', {'success': True, 'result': 'ok'})
	)
	assert (await Agent('t', model, browser=Browser(local=True), workspace=tmp_path).run()).status == 'completed'
	assert 'Feedback is off' in str(seen[-1][-1])
	handler = cli_mcp.CLIMCPServer().server._request_handlers['tools/call'].handler
	call = types.CallToolRequestParams(name='browser_feedback', arguments={'message': 'browser_exec hangs'})
	result = await handler(None, call)  # pyright: ignore[reportArgumentType]
	assert 'Feedback is off' in result.content[0].text and not result.is_error  # pyright: ignore[reportAttributeAccessIssue]
	assert posthog.telemetry._thread is None and not posthog.state.attempts
	assert not [p for p in posthog.config.rglob('*') if p.is_file()]


async def test_the_mcp_feedback_tool_is_listed_and_sends_one_event(posthog):
	from mcp import types

	from browser_use.mcp import cli_mcp

	server = cli_mcp.CLIMCPServer()
	(tool,) = (t for t in server._tool_definitions() if t.name == 'browser_feedback')
	assert tool.input_schema['required'] == ['message'] and 'never include secrets' in tool.description  # pyright: ignore[reportOptionalOperand]
	handler = server.server._request_handlers['tools/call'].handler

	async def call(arguments: dict):
		return await handler(None, types.CallToolRequestParams(name='browser_feedback', arguments=arguments))  # pyright: ignore[reportArgumentType]

	ok = await call({'message': 'js() drops an async return value, see jane@zq9.test', 'category': 'missing'})
	assert not ok.is_error and 'Reported to the Browser Use team' in ok.content[0].text  # pyright: ignore[reportAttributeAccessIssue]
	assert (await call({'message': ' '})).is_error
	events = posthog.events(3)
	(report,) = _feedback(events)
	p = report['properties']
	assert (p['source'], p['category'], p['message']) == ('mcp', 'missing', 'js() drops an async return value, see <email>')
	assert p['run_id'] is None and p['model'] is None
	assert [e['properties']['tool_name'] for e in events if e['event'] == 'mcp_server_event'] == ['browser_feedback'] * 2


def test_the_mcp_feedback_tool_sends_at_most_three_per_server(posthog):
	"""A client model stuck in a loop called browser_feedback every turn: one server process sends three, as
	report_issue() per run, and says the rest were not sent."""
	from browser_use.telemetry import feedback

	texts = [feedback.mcp_call({'message': f'goto_url hangs {i}'}) for i in range(5)]
	assert texts[:3] == [(feedback.SENT, False)] * 3
	assert texts[3:] == [('Already reported 3 issues this session: nothing more was sent.', False)] * 2
	assert [e['properties']['message'] for e in _feedback(posthog.events(3))] == [f'goto_url hangs {i}' for i in range(3)]


def test_python_feedback_is_the_users_consent_sent_with_usage_stats_off_and_nothing_else_with_it(posthog, monkeypatch):
	"""browser_use.feedback() is the developer asking to send it: it goes even with usage stats off, scrubbed of
	credentials but not of their own words, and the events an earlier process kept (outbox) stay unsent."""
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'false')
	outbox = posthog.config / 'telemetry' / 'outbox'
	outbox.mkdir(parents=True)
	(outbox / 'kept.gz').write_bytes(gzip.compress(b'{"batch": []}'))
	assert browser_use.feedback('Agent(mode="ultrafast") ignores sensitive_data, token=Zq9tok in /home/jane/app', 'nope')
	assert not browser_use.feedback('  ')
	(event,) = posthog.events()
	p = event['properties']
	assert (event['event'], event['distinct_id']) == ('library_feedback', 'bu-test-device')
	assert (p['source'], p['category']) == ('python', 'other')
	assert p['message'] == 'Agent(mode="ultrafast") ignores sensitive_data, token=<credential> in /home/<user>/app'
	assert posthog.telemetry.flush() and posthog.state.attempts == 1 and (outbox / 'kept.gz').exists()


FEEDBACK_CLI = """
import sys
import browser_use.telemetry.service as service
service.POSTHOG_HOST = sys.argv[1]
from browser_use.cli import main
sys.argv = ['browser-use', 'feedback', *sys.argv[2:]]
sys.exit(main())
"""


@pytest.mark.parametrize('argv, stdin', [(['--category', 'docs', 'the skill path is wrong'], None), ([], 'piped: wrong path\n')])
def test_cli_feedback_says_it_was_sent_to_the_browser_use_team(posthog, argv, stdin):
	"""`browser-use feedback "..."` (or piped) is the user's own call: sent with usage stats off too, and it says so."""
	import browser_use.telemetry.service as service

	env = {**os.environ, 'ANONYMIZED_TELEMETRY': 'false', 'BROWSER_USE_CONFIG_DIR': str(posthog.config)}
	cmd = [sys.executable, '-c', FEEDBACK_CLI, service.POSTHOG_HOST, *argv]
	r = subprocess.run(cmd, env=env, input=stdin or '', capture_output=True, text=True, timeout=60)
	assert r.returncode == 0, r.stderr[-3000:]
	assert r.stdout == 'Sent your feedback to the Browser Use team. Thanks!\n'
	(event,) = posthog.events()
	p = event['properties']
	assert (event['event'], p['source'], p['category']) == ('library_feedback', 'cli', 'docs' if argv else 'bug')
	assert p['message'] == (stdin or argv[-1]).strip()


MODEL_CELL = """
import subprocess, sys
import browser_use, browser_use.telemetry.service as service
service.POSTHOG_HOST = 'http://127.0.0.1:9'  # nothing listens: a regression fails here, never reaches PostHog
print('queued', browser_use.feedback('model wrote this'))
cli = {cli!r}
r = subprocess.run([sys.executable, '-c', cli], capture_output=True, text=True, timeout=60)
print('cli', r.returncode, r.stdout.strip(), r.stderr.strip())
print(report_issue('goto_url hangs'))
"""


async def test_the_models_code_is_pointed_at_report_issue_not_the_users_feedback_path(posthog, tmp_path, monkeypatch):
	"""Review: a cell (model-written or prompt-injected) could call browser_use.feedback() or `browser-use feedback`,
	the user's path: sent with usage stats off, as the user's report, uncapped and without the task scrub. Under
	BU_MODEL_CODE (agent cells, --cli-mcp and what they start) those send nothing, also with usage stats on, and say to
	use report_issue() or browser_feedback, never that the user turned feedback off. Best effort: the code can unset the
	variable; it keeps the model off the user's path by mistake."""
	import asyncio

	no_browser(monkeypatch)
	cli = (
		"import sys, browser_use.telemetry.service as service\nservice.POSTHOG_HOST = 'http://127.0.0.1:9'\n"
		"from browser_use.cli import main\nsys.argv = ['browser-use', 'feedback', 'cli from a cell']\nsys.exit(main())"
	)
	model, seen = script(('python', {'code': MODEL_CELL.format(cli=cli)}), ('finish', {'success': True, 'result': 'ok'}))
	assert (await Agent('t', model, browser=Browser(local=True), workspace=tmp_path).run()).status == 'completed'
	out = str(seen[-1][-1])
	assert 'queued False' in out and 'cli 1  From an agent cell use report_issue' in out, out
	assert 'Feedback is off' not in out and 'Reported to the Browser Use team' in out, out
	events = posthog.events(2)
	assert [e['properties']['source'] for e in _feedback(events)] == ['agent']
	# --cli-mcp's browser_exec with usage stats on: `browser-use feedback` from its code was sent as the user's (source cli)
	env = {**os.environ, 'ANONYMIZED_TELEMETRY': 'true', 'BU_MODEL_CODE': '1', 'BROWSER_USE_CONFIG_DIR': str(posthog.config)}
	r = await asyncio.to_thread(subprocess.run, [sys.executable, '-c', cli], env=env, capture_output=True, text=True, timeout=60)
	assert (r.returncode, r.stdout) == (1, '') and 'the browser_feedback tool' in r.stderr, r.stderr[-3000:]


@pytest.mark.parametrize('live', [True, False])
def test_feedback_sent_with_usage_stats_off_leaves_no_file_and_no_device_id(posthog, monkeypatch, live):
	"""Review: with usage stats off, browser_use.feedback() stored a device_id, and an exit send that failed left its
	event in the outbox, sent later once stats were on, without asking again. Off, it goes under an id of this process,
	once: the exit sender deletes it, sent or not."""
	import browser_use.telemetry.service as service

	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'false')
	monkeypatch.delenv('BROWSER_USE_DEVICE_ID')
	spawned, popen = [], subprocess.Popen
	monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: spawned.append(a[0]))
	t = posthog.telemetry
	monkeypatch.setattr(t, '_loop', lambda: None)  # still queued when the script exits
	assert browser_use.feedback('Browser(local=True) ignores my profile')
	t._at_exit()
	monkeypatch.setattr(subprocess, 'Popen', popen)
	(cmd,) = spawned
	(arg,) = cmd[5:]
	assert arg.startswith('!') and Path(arg[1:]).exists()
	posthog.state.down = not live
	subprocess.run(cmd, timeout=60, check=True)  # the detached exit sender, run to its end
	assert not Path(arg[1:]).exists() and posthog.state.attempts == 1
	assert not [p for p in posthog.config.rglob('*') if p.is_file()]
	if live:
		(event,) = posthog.events()
		assert event['distinct_id'] == service._PROCESS_ID and event['properties']['source'] == 'python'


def test_feedback_still_queued_at_exit_reaches_posthog_when_the_outbox_cannot_be_written(posthog, monkeypatch):
	"""Daytona: --cli-mcp under a read-only HOME serves browser_feedback (the error server); a client that exits right
	after the call got 'Reported' and the event was lost: still POSTing at exit, and the outbox could not take it, so no
	exit sender started. It goes in a temp file the exit sender sends once."""
	import browser_use.telemetry.service as service
	from browser_use.telemetry import feedback

	posthog.config.write_text('')  # a file: the outbox cannot be made under it
	spawned, popen = [], subprocess.Popen
	monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: spawned.append(a[0]))
	t = posthog.telemetry
	monkeypatch.setattr(t, '_loop', lambda: None)  # still queued when the server exits
	text, failed = feedback.mcp_call({'message': 'browser_exec cannot start under a read-only HOME'})
	assert (text, failed) == (feedback.SENT, False)
	t._at_exit()
	t._at_exit()  # atexit after an explicit call: not handed twice
	monkeypatch.setattr(subprocess, 'Popen', popen)
	(cmd,) = spawned
	(arg,) = cmd[5:]
	assert arg.startswith('!')
	subprocess.run(cmd, timeout=60, check=True)  # the detached exit sender, run to its end
	(event,) = posthog.events()
	assert (event['event'], event['properties']['source']) == ('library_feedback', 'mcp') and not Path(arg[1:]).exists()


def test_an_exit_sender_that_cannot_start_leaves_no_feedback_file(posthog, monkeypatch):
	"""Review: with usage stats off and no subprocess allowed, the temp file holding the user's feedback stayed in TMPDIR
	forever; nothing would ever send or delete it."""
	import tempfile

	import browser_use.telemetry.service as service

	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'false')
	before = set(Path(tempfile.gettempdir()).glob('browser-use-*'))

	def no_subprocess(*args, **kwargs):
		raise OSError('no subprocesses here')

	monkeypatch.setattr(service.subprocess, 'Popen', no_subprocess)
	monkeypatch.setattr(posthog.telemetry, '_loop', lambda: None)
	assert browser_use.feedback('Browser(local=True) ignores my profile')
	posthog.telemetry._at_exit()
	posthog.telemetry._at_exit()
	assert set(Path(tempfile.gettempdir()).glob('browser-use-*')) == before


def test_a_home_outside_users_and_home_is_sent_as_tilde(monkeypatch):
	"""Daytona: HOME=/tmp/h1 went out verbatim in a feedback message; /var/lib/jenkins or /data/users/jane would too."""
	monkeypatch.setenv('HOME', '/data/users/jane')
	monkeypatch.setenv('USERPROFILE', '/data/users/jane')  # Windows: expanduser reads USERPROFILE, not HOME
	text = 'no file /data/users/jane/app/a.pdf, /data/users/janet/x, file:///data/users/jane/y, /Users/bob/z'
	assert scrub(text, [], 500) == 'no file ~/app/a.pdf, /data/users/janet/x, file://~/y, /Users/<user>/z'
