"""BROWSER_USE_OFFLINE=1: nothing goes to Browser Use or PostHog or PyPI, only the user's model endpoint and browser.
Every non-loopback connection this process tries is recorded and refused, so a regression fails here and sends nothing."""

import ipaddress
import socket

import pytest
from conftest import script

import browser_use
from browser_use import Agent, Browser, ChatBrowserUse, ChatOpenAI
from browser_use.llm import GATEWAY_URL
from browser_use.telemetry import feedback
from browser_use.telemetry.service import telemetry

NOT_LOOPBACK = 'http://192.0.2.1:9'  # TEST-NET-1: a regression is recorded here, and could not connect anyway


def _loopback(host: str) -> bool:
	try:
		return ipaddress.ip_address(host.split('%')[0]).is_loopback
	except ValueError:
		return host == 'localhost'


@pytest.fixture
def egress(monkeypatch, tmp_path):
	"""The non-loopback hosts this process looked up or connected to (refused), with telemetry pointed at one."""
	import browser_use.telemetry.service as service

	tried: list[str] = []
	real_getaddrinfo, real_connect = socket.getaddrinfo, socket.socket.connect

	def getaddrinfo(host, *args, **kwargs):
		if host is not None and not _loopback(str(host)):
			tried.append(str(host))
			raise socket.gaierror(f'offline test: {host} is not this machine')
		return real_getaddrinfo(host, *args, **kwargs)

	def connect(self, address):
		if self.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(str(address[0])):
			tried.append(str(address[0]))
			raise OSError(f'offline test: {address[0]} is not this machine')
		return real_connect(self, address)

	monkeypatch.setattr(socket, 'getaddrinfo', getaddrinfo)
	monkeypatch.setattr(socket.socket, 'connect', connect)
	monkeypatch.setattr(service, 'POSTHOG_HOST', NOT_LOOPBACK)
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path / 'config'))  # the outbox of a failed send
	monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'true')  # BROWSER_USE_OFFLINE wins over it
	return tried


async def test_an_offline_run_contacts_nothing_but_this_machine(chrome, tmp_path, monkeypatch, egress):
	monkeypatch.setenv('BROWSER_USE_OFFLINE', '1')
	code = (
		"import os\nnew_tab('data:text/html,<title>Hi</title>'); wait_for_load()\n"
		"env = '|'.join(str(os.environ.get(k)) for k in ('BROWSER_USE_OFFLINE', 'BH_TELEMETRY', 'BH_UPDATE_CHECK'))\n"
		"env += '|' + report_issue('the title helper broke')"
	)
	model, _ = script(('python', {'code': code}), ('finish_from_repl', {'success': True, 'expression': 'env'}))
	result = await Agent('Read the title', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path).run()
	assert result.final_result() == f'1|0|0|{feedback.OFF}'  # the worker carries the switch; report_issue sent nothing
	telemetry().flush(2)
	assert egress == []


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
		(lambda m: Agent('t', browser=Browser('chromium')), 'the model bu-fast (the Browser Use gateway at'),
		(lambda m: Agent('t', 'bu-smart', browser=Browser('chromium')), 'the model bu-smart'),
		(lambda m: Agent('t', ChatOpenAI('gpt-6-luna', base_url=GATEWAY_URL), browser=Browser('chromium')), 'gpt-6-luna'),
		(lambda m: Agent('t', m, browser=Browser('chromium'), web_search=True), 'Agent(web_search=True)'),
	],
)
def test_offline_refuses_browser_use_services_when_constructed(monkeypatch, egress, make, says):
	monkeypatch.setenv('BROWSER_USE_OFFLINE', '1')
	model, _ = script()
	with pytest.raises(ValueError, match='^BROWSER_USE_OFFLINE=1: ') as e:
		make(model)
	assert says in str(e.value) and 'unset BROWSER_USE_OFFLINE' in str(e.value)
	assert egress == []


def test_offline_allows_your_own_model_endpoint_and_browser(monkeypatch, egress):
	monkeypatch.setenv('BROWSER_USE_OFFLINE', '1')
	model, _ = script()
	Agent('t', model, browser=Browser('chromium'))
	Agent('t', ChatOpenAI('llama', base_url='http://127.0.0.1:11434/v1', api_key='x'), browser=Browser('chrome'))
	Agent('t', ChatBrowserUse('bu-fast', base_url='https://llm.corp.example/v1', api_key='bu_x'), browser=Browser('chromium'))
	assert egress == []


def test_offline_refuses_a_cloud_browser_from_the_cli(monkeypatch, egress):
	from browser_use import harness_cloud

	monkeypatch.setenv('BROWSER_USE_OFFLINE', '1')
	with pytest.raises(harness_cloud.CloudBrowserError, match='BROWSER_USE_OFFLINE=1: start_remote_daemon'):
		harness_cloud.start('offline-test', None, {}, None)
	assert egress == []
