"""BROWSER_USE_OFFLINE=1: nothing goes to Browser Use or PostHog or PyPI, only the user's model endpoint and browser.
Every non-loopback lookup or connection is recorded and refused, in this process and, through a sitecustomize, in every
Python process it starts (the REPL worker, the browser-harness daemon): a regression fails here and sends nothing."""

import os
import socket
from pathlib import Path

import pytest
from conftest import script

import browser_use
from browser_use import Agent, Browser, ChatBrowserUse, ChatOpenAI
from browser_use.llm import GATEWAY_URL
from browser_use.telemetry import feedback
from browser_use.telemetry.service import telemetry

NOT_LOOPBACK = 'http://192.0.2.1:9'  # TEST-NET-1: a regression is recorded here, and could not connect anyway
GUARD = """
import ipaddress, socket

def _loopback(host):
	try:
		return ipaddress.ip_address(host.split('%')[0]).is_loopback
	except ValueError:
		return host == 'localhost'

real_getaddrinfo, real_connect, real_connect_ex = socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex

def getaddrinfo(host, *args, **kwargs):
	if host is not None and not _loopback(str(host)):
		record(str(host))
		raise socket.gaierror(f'offline test: {host} is not this machine')
	return real_getaddrinfo(host, *args, **kwargs)

def _refuse(sock, address):
	if sock.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(str(address[0])):
		record(str(address[0]))
		raise OSError(f'offline test: {address[0]} is not this machine')

def connect(self, address):
	_refuse(self, address)
	return real_connect(self, address)

def connect_ex(self, address):
	_refuse(self, address)
	return real_connect_ex(self, address)
"""
SITECUSTOMIZE = (  # the same guard in each child process, writing to the file in BU_TEST_EGRESS (BU_*: the worker gets it)
	'import os, sys\n'
	'def record(line, log=os.environ.get("BU_TEST_EGRESS")):\n'
	'\twith open(log, "a") as f:\n'
	'\t\tf.write(line + "\\n")\n'
	'if os.environ.get("BU_TEST_EGRESS"):\n'
	'\texec(GUARD)\n'
	'\tsocket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex = getaddrinfo, connect, connect_ex\n'
	'\trecord("started " + " ".join(sys.orig_argv).replace("\\n", " "))\n'  # one line: `python -c <script>` too
)


@pytest.fixture
def egress(monkeypatch, tmp_path):
	"""The non-loopback hosts this process looked up or connected to (refused), with telemetry pointed at one. Child
	processes record theirs, and a line per process started, in tmp_path / 'egress.log' (children())."""
	import browser_use.telemetry.service as service

	tried: list[str] = []
	guard: dict = {'record': tried.append}
	exec(GUARD, guard)
	monkeypatch.setattr(socket, 'getaddrinfo', guard['getaddrinfo'])
	monkeypatch.setattr(socket.socket, 'connect', guard['connect'])
	monkeypatch.setattr(socket.socket, 'connect_ex', guard['connect_ex'])
	site = tmp_path / 'site'
	site.mkdir()
	(site / 'sitecustomize.py').write_text(f'GUARD = {GUARD!r}\n{SITECUSTOMIZE}')
	monkeypatch.setenv('PYTHONPATH', os.pathsep.join(filter(None, [str(site), os.environ.get('PYTHONPATH')])))
	monkeypatch.setenv('BU_TEST_EGRESS', str(tmp_path / 'egress.log'))
	monkeypatch.setattr(service, 'POSTHOG_HOST', NOT_LOOPBACK)
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path / 'config'))  # the outbox of a failed send
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'true')  # BROWSER_USE_OFFLINE wins over it
	return tried


def children(tmp_path: Path) -> tuple[list[str], list[str]]:
	"""(command lines of the Python processes started, non-loopback hosts they tried) from the egress fixture's log."""
	lines = (tmp_path / 'egress.log').read_text().splitlines() if (tmp_path / 'egress.log').exists() else []
	started = [line.removeprefix('started ') for line in lines if line.startswith('started ')]
	return started, [line for line in lines if not line.startswith('started ')]


async def test_an_offline_run_contacts_nothing_but_this_machine(chrome, tmp_path, monkeypatch, egress):
	monkeypatch.setenv('BROWSER_USE_OFFLINE', '1')
	code = (
		"import os\nnew_tab('data:text/html,<title>Hi</title>'); wait_for_load()\n"
		"env = '|'.join(str(os.environ.get(k)) for k in ('BROWSER_USE_OFFLINE', 'BH_TELEMETRY', 'BH_UPDATE_CHECK'))\n"
		"env += '|' + report_issue('the title helper broke')\n"
		"try: http_get('http://control.invalid/')  # control: the worker's guard records this one\n"
		'except OSError: pass'
	)
	model, _ = script(('python', {'code': code}), ('finish_from_repl', {'success': True, 'expression': 'env'}))
	result = await Agent('Read the title', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path).run()
	assert result.final_result() == f'1|0|0|{feedback.OFF}'  # the worker carries the switch; report_issue sent nothing
	telemetry().flush(2)
	assert egress == []
	started, tried = children(tmp_path)
	assert any('browser_use.repl.worker' in c for c in started) and any('browser_harness.daemon' in c for c in started)
	assert tried == ['control.invalid']


def test_feedback_the_user_sends_is_not_sent_offline(monkeypatch, egress):
	assert browser_use.feedback('control: sent without the switch')  # the user's own feedback, with usage stats on
	telemetry().flush(5)
	assert egress  # what a send looks like to the recorder
	egress.clear()
	monkeypatch.setenv('BROWSER_USE_OFFLINE', '1')
	assert not browser_use.feedback('goto_url hangs')
	assert not telemetry().enabled
	telemetry().flush(2)
	assert egress == []


def test_cli_offline_turns_off_browser_harness_and_feedback(monkeypatch, capsys, egress):
	from browser_use import cli

	monkeypatch.setenv('BROWSER_USE_OFFLINE', '1')
	monkeypatch.setenv('BH_TELEMETRY', '1')
	monkeypatch.setenv('BH_UPDATE_CHECK', '1')
	monkeypatch.setattr('sys.argv', ['browser-use', 'feedback', 'goto_url hangs'])
	assert cli.main() == 1
	assert 'BROWSER_USE_OFFLINE=1: nothing was sent.' in capsys.readouterr().err
	import os

	assert (os.environ['BH_TELEMETRY'], os.environ['BH_UPDATE_CHECK']) == ('0', '0')  # every browser-harness it starts
	assert egress == []


def test_offline_skips_the_pypi_update_check(monkeypatch):
	import browser_use.utils
	from browser_use import update_check

	asked = []
	monkeypatch.setattr(update_check, '_latest', lambda: asked.append(1) or '99.0.0')
	monkeypatch.setattr(browser_use.utils, 'get_install_source', lambda: 'pip')
	monkeypatch.delenv('CI', raising=False)
	monkeypatch.delenv('BROWSER_USE_NO_UPDATE_CHECK', raising=False)
	assert '99.0.0' in update_check.upgrade_hint(RuntimeError('x')) and asked == [1]  # control: it asks PyPI
	monkeypatch.setenv('BROWSER_USE_OFFLINE', '1')
	assert update_check.upgrade_hint(RuntimeError('x')) == '' and asked == [1]


@pytest.mark.parametrize(
	'make, says',
	[
		(lambda m: Agent('t', m), 'Browser() (a Browser Use Cloud browser, the default)'),
		(lambda m: Browser(cloud_profile_id='work'), 'Browser() (a Browser Use Cloud browser, the default)'),
		(lambda m: Agent('t', browser=Browser('chromium')), 'the model bu-fast (served by Browser Use at'),
		(lambda m: Agent('t', 'bu-smart', browser=Browser('chromium')), 'the model bu-smart'),
		(lambda m: Agent('t', ChatOpenAI('gpt-6-luna', base_url=GATEWAY_URL), browser=Browser('chromium')), 'gpt-6-luna'),
		(lambda m: Agent('t', m, browser=Browser('chromium'), web_search=True), 'Agent(web_search=True)'),
		# not the gateway's exact URL, still Browser Use's host
		(
			lambda m: Agent(
				't', ChatOpenAI('x', base_url='http://api.browser-use.com/v1', api_key='k'), browser=Browser('chromium')
			),
			'the model x',
		),
		(lambda m: Agent('t', _pydantic_model(GATEWAY_URL), browser=Browser('chromium')), 'the model gpt-6-luna'),
		(lambda m: Browser(cdp_url='wss://cdp.browser-use.com/devtools/browser/1'), 'a cdp_url on browser-use.com'),
	],
)
def test_offline_refuses_browser_use_services_when_constructed(monkeypatch, egress, make, says):
	monkeypatch.setenv('BROWSER_USE_OFFLINE', '1')
	model, _ = script()
	with pytest.raises(ValueError, match='^BROWSER_USE_OFFLINE=1: ') as e:
		make(model)
	assert says in str(e.value) and 'unset BROWSER_USE_OFFLINE' in str(e.value)
	assert egress == []


def _pydantic_model(base_url: str):
	from pydantic_ai.models.openai import OpenAIChatModel
	from pydantic_ai.providers.openai import OpenAIProvider

	return OpenAIChatModel('gpt-6-luna', provider=OpenAIProvider(base_url=base_url, api_key='k'))


def test_offline_allows_your_own_model_endpoint_and_browser(monkeypatch, egress):
	monkeypatch.setenv('BROWSER_USE_OFFLINE', '1')
	model, _ = script()
	Agent('t', model, browser=Browser('chromium'))
	Agent('t', _pydantic_model('http://127.0.0.1:8000/v1'), browser=Browser(cdp_url='http://127.0.0.1:9222'))
	Agent('t', ChatOpenAI('llama', base_url='http://127.0.0.1:11434/v1', api_key='x'), browser=Browser('chrome'))
	Agent('t', ChatBrowserUse('bu-fast', base_url='https://llm.corp.example/v1', api_key='bu_x'), browser=Browser('chromium'))
	assert egress == []


def test_offline_refuses_a_cloud_browser_from_the_cli(monkeypatch, egress):
	from browser_use import harness_cloud

	monkeypatch.setenv('BROWSER_USE_OFFLINE', '1')
	with pytest.raises(harness_cloud.CloudBrowserError, match='BROWSER_USE_OFFLINE=1: start_remote_daemon'):
		harness_cloud.start('offline-test', None, {}, None)
	assert egress == []


def test_offline_mcp_browser_login_contacts_nothing(monkeypatch, egress):
	from browser_use.mcp import cli_mcp

	monkeypatch.setenv('BROWSER_USE_OFFLINE', '1')
	monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)
	monkeypatch.setattr(cli_mcp, '_open_url', lambda url: pytest.fail(f'opened {url}'))  # never a real browser
	text = cli_mcp.CLIMCPServer()._sign_in(force=True, wait=0.2)  # the client model asks, not the user
	assert text.startswith('BROWSER_USE_OFFLINE=1: browser_login would contact Browser Use')
	assert egress == []


@pytest.mark.parametrize('helper', ['list_cloud_profiles', 'sync_local_profile'])
def test_offline_refuses_cloud_profile_helpers_in_cli_code(monkeypatch, egress, helper):
	from browser_harness import run

	from browser_use import cli, harness_cloud

	monkeypatch.setenv('BROWSER_USE_OFFLINE', '1')
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'bu_test')  # signed in: browser-harness would call the cloud API
	for name in ('ensure_daemon', 'upload_file', 'start_remote_daemon', 'stop_remote_daemon', helper):
		monkeypatch.setitem(vars(run), name, vars(run)[name])  # the guards below are undone after the test
	cli._guard_cloud_browsers(run, None)  # what piped code runs in
	with pytest.raises(harness_cloud.CloudBrowserError, match=f'^BROWSER_USE_OFFLINE=1: {helper}\\(\\) would contact'):
		vars(run)[helper]('Default')
	assert egress == []


def test_offline_does_not_download_chromium(monkeypatch, egress):
	import subprocess

	from browser_use.mcp import cli_mcp

	monkeypatch.setenv('BROWSER_USE_OFFLINE', '1')
	monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail(f'ran {a}'))
	with pytest.raises(RuntimeError, match='BROWSER_USE_OFFLINE=1 does not download one'):
		cli_mcp._install_chromium()  # the CLI and --cli-mcp, on a machine with no browser and no display
	assert egress == []
