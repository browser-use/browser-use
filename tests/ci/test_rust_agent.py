from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel


def _load_real_v8_smoke_module():
	path = Path(__file__).parents[2] / 'examples' / 'rust_agent' / 'real_v8_smoke.py'
	spec = importlib.util.spec_from_file_location('real_v8_smoke', path)
	assert spec is not None
	assert spec.loader is not None
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def test_top_level_agent_uses_rust_wrapper():
	from browser_use import Agent as TopLevelAgent
	from browser_use.rust import Agent as RustAgent

	assert TopLevelAgent is RustAgent


def test_agent_package_export_uses_rust_wrapper():
	from browser_use.agent import Agent as AgentPackageAgent
	from browser_use.rust import Agent as RustAgent

	assert AgentPackageAgent is RustAgent


def test_rust_events_reconstruct_browser_use_history():
	from browser_use.rust.service import _history_from_events

	events = [
		{
			'event_type': 'browser.state',
			'payload': {'url': 'https://example.com', 'title': 'Example'},
		},
		{
			'event_type': 'model.usage',
			'payload': {'input_tokens': 11, 'cached_input_tokens': 3, 'output_tokens': 7, 'cost_usd': 0.12},
		},
		{
			'event_type': 'session.done',
			'payload': {'result': 'final answer'},
		},
	]

	history = _history_from_events(
		events,
		model='gpt-test',
		started=1.0,
		finished=2.5,
		output_model_schema=None,
		process_error=None,
	)

	assert history.final_result() == 'final answer'
	assert history.is_done() is True
	assert history.is_successful() is True
	assert history.urls() == ['https://example.com']
	assert history.usage is not None
	assert history.usage.total_prompt_tokens == 11
	assert history.usage.total_prompt_cached_tokens == 3
	assert history.usage.total_completion_tokens == 7


def test_rust_history_supports_structured_output():
	from browser_use.rust.service import _history_from_events

	class Answer(BaseModel):
		answer: str

	history = _history_from_events(
		[{'event_type': 'session.done', 'payload': {'result': '{"answer": "ok"}'}}],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=Answer,
		process_error=None,
	)

	assert isinstance(history.structured_output, Answer)
	assert history.structured_output.answer == 'ok'


def test_rust_history_extracts_fenced_structured_output():
	from browser_use.rust.service import _history_from_events

	class Answer(BaseModel):
		answer: str

	history = _history_from_events(
		[{'event_type': 'session.done', 'payload': {'result': 'Here is the answer:\n```json\n{"answer": "ok"}\n```'}}],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=Answer,
		process_error=None,
	)

	assert history.final_result() == '{"answer": "ok"}'
	assert isinstance(history.structured_output, Answer)
	assert history.structured_output.answer == 'ok'


def test_rust_history_exposes_result_file_attachments():
	from browser_use.rust.service import _history_from_events

	history = _history_from_events(
		[
			{
				'event_type': 'session.done',
				'payload': {
					'result': 'Saved structured report.',
					'result_file': {'url': 'file:///tmp/report.json', 'path': '/tmp/report.json', 'bytes': 123},
				},
			}
		],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	results = history.action_results()

	assert history.final_result() == 'Saved structured report.'
	assert results[0].attachments == ['file:///tmp/report.json']


def test_rust_agent_translates_browser_use_args_to_terminal(monkeypatch):
	from browser_use.rust import Agent

	class LLM:
		model = 'gpt-test'

	class Browser:
		cdp_url = 'wss://browser.example/devtools/browser/1'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	agent = Agent(
		task='report title',
		llm=LLM(),
		browser_session=Browser(),
		initial_actions=[{'go_to_url': {'url': 'https://example.com'}}],
	)

	argv = agent._run_argv(max_steps=12)
	env = agent._run_env()

	assert argv[0] == '/tmp/browser-use-terminal'
	assert argv[-4:] == ['run-codex', agent.task, '--model', 'gpt-test']
	assert '-c' in argv
	assert 'max_turns=12' in argv
	assert 'browser_mode="remote-cdp"' in argv
	assert "First navigate to 'https://example.com'" in agent.task
	assert env['BU_CDP_URL'] == 'wss://browser.example/devtools/browser/1'
	assert env['LLM_BROWSER_BROWSER_MODE'] == 'remote-cdp'


def test_rust_agent_translates_browser_profile_cdp_url(monkeypatch):
	from browser_use.rust import Agent

	class BrowserProfile:
		cdp_url = 'http://127.0.0.1:9222'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert 'browser_mode="remote-cdp"' in agent._run_argv(max_steps=4)
	assert env['BU_CDP_URL'] == 'http://127.0.0.1:9222'
	assert env['LLM_BROWSER_BROWSER_MODE'] == 'remote-cdp'


def test_rust_agent_translates_browser_profile_cdp_headers(monkeypatch):
	from browser_use.rust import Agent

	class BrowserProfile:
		cdp_url = 'http://127.0.0.1:9222'
		headers = {'Authorization': 'Bearer test-token', 'X-Browser-Use': 'rust', 'Retries': 3}

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'remote-cdp'
	assert agent.cdp_headers == {
		'Authorization': 'Bearer test-token',
		'X-Browser-Use': 'rust',
		'Retries': '3',
	}
	assert json.loads(env['BU_CDP_HEADERS']) == agent.cdp_headers


def test_rust_agent_translates_browser_profile_remote_user_agent(monkeypatch):
	from browser_use.rust import Agent

	class BrowserProfile:
		cdp_url = 'http://127.0.0.1:9222'
		user_agent = 'BrowserUseRemote/2.0'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'remote-cdp'
	assert agent.browser_user_agent == 'BrowserUseRemote/2.0'
	assert env['BU_BROWSER_USER_AGENT'] == 'BrowserUseRemote/2.0'


def test_rust_agent_translates_browser_profile_highlights(monkeypatch):
	from browser_use.rust import Agent

	class BrowserProfile:
		highlight_elements = True
		dom_highlight_elements = False
		interaction_highlight_color = 'rgb(255, 127, 39)'
		interaction_highlight_duration = 1.75
		cdp_url = 'http://127.0.0.1:9222'

	class DomHighlightProfile:
		highlight_elements = True
		dom_highlight_elements = True
		cdp_url = 'http://127.0.0.1:9222'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['BROWSER_USE_TERMINAL_AUTO_HIGHLIGHT'] == 'true'
	assert env['BROWSER_USE_TERMINAL_HIGHLIGHT_COLOR'] == 'rgb(255, 127, 39)'
	assert env['BROWSER_USE_TERMINAL_HIGHLIGHT_DURATION_MS'] == '1750'

	dom_agent = Agent(task='report title', browser_profile=DomHighlightProfile())
	dom_env = dom_agent._run_env()

	assert dom_agent.highlight_enabled is False
	assert dom_env['BROWSER_USE_TERMINAL_AUTO_HIGHLIGHT'] == 'false'


def test_rust_agent_translates_browser_profile_wait_timings(monkeypatch):
	from browser_use.rust import Agent

	class BrowserProfile:
		minimum_wait_page_load_time = 0.25
		wait_for_network_idle_page_load_time = 0.75
		wait_between_actions = 0.125
		cdp_url = 'http://127.0.0.1:9222'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert agent.wait_timing_env == {
		'BU_BROWSER_MINIMUM_WAIT_PAGE_LOAD_MS': '250',
		'BU_BROWSER_NETWORK_IDLE_PAGE_LOAD_MS': '750',
		'BU_BROWSER_WAIT_BETWEEN_ACTIONS_MS': '125',
	}
	assert env['BU_BROWSER_MINIMUM_WAIT_PAGE_LOAD_MS'] == '250'
	assert env['BU_BROWSER_NETWORK_IDLE_PAGE_LOAD_MS'] == '750'
	assert env['BU_BROWSER_WAIT_BETWEEN_ACTIONS_MS'] == '125'


def test_rust_agent_translates_browser_profile_block_ip_addresses(monkeypatch):
	from browser_use.rust import Agent

	class BrowserProfile:
		block_ip_addresses = True
		cdp_url = 'http://127.0.0.1:9222'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert agent.block_ip_addresses is True
	assert env['BU_BROWSER_BLOCK_IP_ADDRESSES'] == 'true'


def test_rust_agent_translates_browser_profile_headless(monkeypatch):
	from browser_use.rust import Agent

	class HeadedProfile:
		headless = False

	class HeadlessProfile:
		headless = True

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	headed = Agent(task='report title', browser_profile=HeadedProfile())
	headless = Agent(task='report title', browser_profile=HeadlessProfile())

	assert 'browser_mode="managed-headed"' in headed._run_argv(max_steps=4)
	assert headed._run_env()['LLM_BROWSER_BROWSER_MODE'] == 'managed-headed'
	assert 'browser_mode="managed-headless"' in headless._run_argv(max_steps=4)
	assert headless._run_env()['LLM_BROWSER_BROWSER_MODE'] == 'managed-headless'


def test_rust_agent_browser_mode_env_overrides_profile_headless(monkeypatch):
	from browser_use.rust import Agent

	class HeadedProfile:
		headless = False

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.setenv('BROWSER_USE_BROWSER_MODE', 'cloud')

	agent = Agent(task='report title', browser_profile=HeadedProfile())

	assert 'browser_mode="cloud"' in agent._run_argv(max_steps=4)
	assert agent._run_env()['LLM_BROWSER_BROWSER_MODE'] == 'cloud'


def test_rust_agent_translates_browser_profile_cloud(monkeypatch):
	from browser_use.rust import Agent

	class CloudProfile:
		use_cloud = True
		headless = False

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	agent = Agent(task='report title', browser_profile=CloudProfile())

	assert 'browser_mode="cloud"' in agent._run_argv(max_steps=4)
	assert agent._run_env()['LLM_BROWSER_BROWSER_MODE'] == 'cloud'


def test_rust_agent_translates_browser_profile_managed_launch_args(monkeypatch):
	from browser_use.rust import Agent

	class Proxy:
		server = 'http://proxy.example:8080'
		bypass = 'localhost,127.0.0.1'

	class BrowserProfile:
		headless = True
		args = ['--lang=en-US']
		disable_security = True
		proxy = Proxy()
		window_size = {'width': 1440, 'height': 900}
		user_agent = 'BrowserUseTest/1.0'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()
	launch_args = json.loads(env['BU_MANAGED_BROWSER_ARGS'])

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'managed-headless'
	assert agent.managed_browser_args == launch_args
	assert agent.browser_user_agent == 'BrowserUseTest/1.0'
	assert env['BU_BROWSER_USER_AGENT'] == 'BrowserUseTest/1.0'
	assert '--lang=en-US' in launch_args
	assert '--window-size=1440,900' in launch_args
	assert '--proxy-server=http://proxy.example:8080' in launch_args
	assert '--proxy-bypass-list=localhost,127.0.0.1' in launch_args
	assert '--disable-web-security' in launch_args
	assert '--user-agent=BrowserUseTest/1.0' in launch_args


def test_rust_agent_translates_browser_profile_chromium_sandbox(monkeypatch):
	from browser_use.rust import Agent

	class BrowserProfile:
		headless = True
		chromium_sandbox = False
		args = ['--no-sandbox']

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	launch_args = json.loads(agent._run_env()['BU_MANAGED_BROWSER_ARGS'])

	assert launch_args.count('--no-sandbox') == 1
	assert '--disable-gpu-sandbox' in launch_args
	assert '--disable-setuid-sandbox' in launch_args
	assert '--disable-dev-shm-usage' in launch_args


def test_rust_agent_translates_browser_profile_window_position(monkeypatch):
	from browser_use.rust import Agent

	class BrowserProfile:
		headless = False
		window_position = {'width': 32, 'height': 64}

	class TuplePositionProfile:
		headless = False
		window_position = (12, 24)

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	tuple_agent = Agent(task='report title', browser_profile=TuplePositionProfile())

	assert '--window-position=32,64' in json.loads(agent._run_env()['BU_MANAGED_BROWSER_ARGS'])
	assert '--window-position=12,24' in json.loads(tuple_agent._run_env()['BU_MANAGED_BROWSER_ARGS'])


def test_rust_agent_translates_browser_profile_devtools(monkeypatch):
	from browser_use.rust import Agent

	class BrowserProfile:
		headless = False
		devtools = True

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()
	launch_args = json.loads(env['BU_MANAGED_BROWSER_ARGS'])

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'managed-headed'
	assert '--auto-open-devtools-for-tabs' in launch_args


def test_rust_agent_translates_browser_profile_profile_directory(monkeypatch):
	from browser_use.rust import Agent

	class BrowserProfile:
		headless = False
		profile_directory = 'Profile 7'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	launch_args = json.loads(agent._run_env()['BU_MANAGED_BROWSER_ARGS'])

	assert '--profile-directory=Profile 7' in launch_args


def test_rust_agent_translates_browser_profile_permissions(monkeypatch):
	from browser_use.rust import Agent

	class BrowserProfile:
		permissions = ['clipboardReadWrite', 'notifications', 'clipboardReadWrite']
		cdp_url = 'http://127.0.0.1:9222'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'remote-cdp'
	assert agent.browser_permissions == ['clipboardReadWrite', 'notifications']
	assert json.loads(env['BU_BROWSER_PERMISSIONS']) == ['clipboardReadWrite', 'notifications']


def test_rust_agent_translates_browser_profile_downloads(monkeypatch, tmp_path):
	from browser_use.rust import Agent

	profile_downloads_path = tmp_path / 'downloads'

	class BrowserProfile:
		accept_downloads = True
		downloads_path = profile_downloads_path
		cdp_url = 'http://127.0.0.1:9222'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'remote-cdp'
	assert agent.browser_accept_downloads is True
	assert agent.browser_downloads_path == str(profile_downloads_path)
	assert env['BU_BROWSER_ACCEPT_DOWNLOADS'] == 'true'
	assert env['BU_BROWSER_DOWNLOADS_PATH'] == str(profile_downloads_path)


def test_rust_agent_translates_browser_profile_viewport(monkeypatch):
	from browser_use.rust import Agent

	class BrowserProfile:
		viewport = {'width': 1024, 'height': 768}
		screen = (1440, 900)
		device_scale_factor = 2
		no_viewport = False
		cdp_url = 'http://127.0.0.1:9222'

	class NoViewportProfile:
		viewport = {'width': 1024, 'height': 768}
		no_viewport = True
		cdp_url = 'http://127.0.0.1:9222'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()
	viewport = json.loads(env['BU_BROWSER_VIEWPORT'])

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'remote-cdp'
	assert env['BU_BROWSER_NO_VIEWPORT'] == 'false'
	assert viewport == {
		'width': 1024,
		'height': 768,
		'deviceScaleFactor': 2,
		'screenWidth': 1440,
		'screenHeight': 900,
	}

	no_viewport_agent = Agent(task='report title', browser_profile=NoViewportProfile())
	no_viewport_env = no_viewport_agent._run_env()

	assert no_viewport_env['BU_BROWSER_NO_VIEWPORT'] == 'true'
	assert 'BU_BROWSER_VIEWPORT' not in no_viewport_env


def test_rust_agent_translates_browser_profile_storage_state(monkeypatch, tmp_path):
	from browser_use.rust import Agent

	profile_storage_state_path = tmp_path / 'storage_state.json'
	storage_state = {
		'cookies': [
			{
				'name': 'sid',
				'value': 'secret',
				'domain': '.example.com',
				'path': '/',
			}
		],
		'origins': [
			{
				'origin': 'https://example.com',
				'localStorage': [{'name': 'theme', 'value': 'dark'}],
			}
		],
	}
	profile_storage_state_path.write_text(json.dumps(storage_state))

	class BrowserProfile:
		storage_state = profile_storage_state_path
		cdp_url = 'http://127.0.0.1:9222'

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'remote-cdp'
	assert agent.browser_storage_state == storage_state
	assert json.loads(env['BU_BROWSER_STORAGE_STATE']) == storage_state


def test_rust_agent_translates_browser_profile_user_data_dir(monkeypatch, tmp_path):
	from browser_use.rust import Agent

	profile_dir = tmp_path / 'browser profile'

	class BrowserProfile:
		headless = False
		user_data_dir = profile_dir

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BU_MANAGED_BROWSER_PROFILE', raising=False)

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'managed-headed'
	assert agent.managed_browser_profile_dir == str(profile_dir)
	assert env['BU_MANAGED_BROWSER_PROFILE'] == str(profile_dir)


def test_rust_agent_translates_browser_profile_executable_path(monkeypatch, tmp_path):
	from browser_use.rust import Agent

	chrome_path = tmp_path / 'custom chrome'

	class BrowserProfile:
		headless = True
		executable_path = chrome_path

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.setenv('CHROME_PATH', '/usr/bin/existing-chrome')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'managed-headless'
	assert agent.managed_browser_executable_path == str(chrome_path)
	assert env['CHROME_PATH'] == str(chrome_path)

	monkeypatch.setenv('BROWSER_USE_BROWSER_MODE', 'cloud')
	cloud_agent = Agent(task='report title', browser_profile=BrowserProfile())
	cloud_env = cloud_agent._run_env()

	assert cloud_env['LLM_BROWSER_BROWSER_MODE'] == 'cloud'
	assert cloud_env['CHROME_PATH'] == '/usr/bin/existing-chrome'


def test_rust_agent_translates_browser_profile_env(monkeypatch):
	from browser_use.rust import Agent

	class BrowserProfile:
		headless = True
		env = {
			'BU_BROWSER_FLAG': 'enabled',
			'BU_BROWSER_BOOL': True,
			'BU_BROWSER_RETRIES': 3,
			'IGNORED_NESTED': {'nested': 'value'},
		}

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	monkeypatch.setenv('BU_BROWSER_FLAG', 'outer')
	monkeypatch.delenv('BROWSER_USE_RUST_BROWSER_MODE', raising=False)
	monkeypatch.delenv('BROWSER_USE_BROWSER_MODE', raising=False)

	agent = Agent(task='report title', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert env['LLM_BROWSER_BROWSER_MODE'] == 'managed-headless'
	assert agent.managed_browser_env == {
		'BU_BROWSER_FLAG': 'enabled',
		'BU_BROWSER_BOOL': 'true',
		'BU_BROWSER_RETRIES': '3',
	}
	assert env['BU_BROWSER_FLAG'] == 'enabled'
	assert env['BU_BROWSER_BOOL'] == 'true'
	assert env['BU_BROWSER_RETRIES'] == '3'
	assert 'IGNORED_NESTED' not in env

	monkeypatch.setenv('BROWSER_USE_BROWSER_MODE', 'cloud')
	cloud_agent = Agent(task='report title', browser_profile=BrowserProfile())
	cloud_env = cloud_agent._run_env()

	assert cloud_env['LLM_BROWSER_BROWSER_MODE'] == 'cloud'
	assert cloud_env['BU_BROWSER_FLAG'] == 'outer'
	assert 'BU_BROWSER_BOOL' not in cloud_env


def test_rust_agent_adds_browser_profile_domain_constraints():
	from browser_use.rust import Agent

	class BrowserProfile:
		allowed_domains = ['example.com', '*.browser-use.com']
		prohibited_domains = {'ads.example.com'}

	agent = Agent(task='Open the allowed site.', browser_profile=BrowserProfile())
	env = agent._run_env()

	assert agent.allowed_domains == ['example.com', '*.browser-use.com']
	assert agent.prohibited_domains == ['ads.example.com']
	assert json.loads(env['BU_BROWSER_ALLOWED_DOMAINS']) == ['example.com', '*.browser-use.com']
	assert json.loads(env['BU_BROWSER_PROHIBITED_DOMAINS']) == ['ads.example.com']
	assert 'Browser profile navigation constraints:' in agent.task
	assert 'Allowed domains:' in agent.task
	assert '- example.com' in agent.task
	assert '- *.browser-use.com' in agent.task
	assert 'Prohibited domains:' in agent.task
	assert '- ads.example.com' in agent.task


def test_rust_agent_adds_sensitive_data_placeholders_without_values():
	from browser_use.rust import Agent

	agent = Agent(
		task='Log in to the portal.',
		sensitive_data={
			'username': 'alice@example.com',
			'https://example.com': {'password': 'super-secret-password'},
		},
	)

	assert agent.sensitive_data_context == {
		'global_placeholders': ['username'],
		'domain_placeholders': {'https://example.com': ['password']},
	}
	assert 'Sensitive data placeholders are available.' in agent.task
	assert '- username' in agent.task
	assert '- https://example.com: password' in agent.task
	assert '<secret>placeholder</secret>' in agent.task
	assert 'alice@example.com' not in agent.task
	assert 'super-secret-password' not in agent.task


def test_rust_agent_mirrors_direct_url_startup():
	from browser_use.rust import Agent

	agent = Agent(task='Open example.com and report the title.')

	assert agent.initial_url == 'https://example.com'
	assert agent.initial_action_payloads == [{'navigate': {'url': 'https://example.com', 'new_tab': False}}]
	assert agent.initial_actions[0].model_dump(exclude_unset=True) == {
		'navigate': {'url': 'https://example.com', 'new_tab': False}
	}
	assert "First navigate to 'https://example.com'" in agent.task


def test_rust_agent_exposes_task_helper_methods():
	from browser_use.rust import Agent

	class Answer(BaseModel):
		answer: str

	agent = Agent(task='Open example.com and report the title.')

	enhanced = agent._enhance_task_with_schema('Return the answer.', Answer)

	assert agent._enhance_task_with_schema('Return the answer.', None) == 'Return the answer.'
	assert 'Expected output format: Answer' in enhanced
	assert '"answer"' in enhanced
	assert agent._extract_start_url('Open example.com and report the title.') == 'https://example.com'
	assert agent._extract_start_url('Email support@example.com only.') is None
	assert agent._extract_start_url('Open https://example.com/report.pdf and summarize it.') is None


def test_rust_agent_preserves_ordered_initial_actions_context():
	from browser_use.rust import Agent

	agent = Agent(
		task='Report what is visible after setup.',
		initial_actions=[
			{'navigate': {'url': 'https://example.com', 'new_tab': False}},
			{'click_element_by_index': {'index': 3}},
		],
	)
	converted = [action.model_dump(exclude_unset=True) for action in agent.initial_actions]

	assert agent.initial_action_payloads == [
		{'navigate': {'url': 'https://example.com', 'new_tab': False}},
		{'click_element_by_index': {'index': 3}},
	]
	assert converted == [
		{'navigate': {'url': 'https://example.com', 'new_tab': False}},
		{'click': {'index': 3}},
	]
	assert 'Browser Use initial actions in order' in agent.task
	assert '"navigate"' in agent.task
	assert '"click_element_by_index"' in agent.task
	assert 'https://example.com' in agent.task
	assert 'Then complete the task.' in agent.task


def test_rust_agent_skips_ambiguous_or_excluded_direct_urls():
	from browser_use.rust import Agent

	ambiguous = Agent(task='Compare example.com and browser-use.com.')
	document = Agent(task='Open https://example.com/report.pdf and summarize it.')

	assert ambiguous.initial_url is None
	assert 'First navigate to' not in ambiguous.task
	assert document.initial_url is None
	assert 'First navigate to' not in document.task


def test_rust_agent_exposes_browser_use_settings():
	from browser_use.rust import Agent

	agent = Agent(
		task='Open example.com',
		use_vision=False,
		max_actions_per_step=2,
		directly_open_url=False,
		available_file_paths=['/tmp/report.txt'],
		file_system_path='/tmp/browser-use-files',
		include_recent_events=True,
	)

	assert agent.initial_url is None
	assert agent.settings.use_vision is False
	assert agent.settings.max_actions_per_step == 2
	assert agent.directly_open_url is False
	assert agent.available_file_paths == ['/tmp/report.txt']
	assert agent.file_system_path == '/tmp/browser-use-files'
	assert agent.include_recent_events is True


def test_rust_agent_initializes_tools_and_action_models():
	from browser_use.rust import Agent
	from browser_use.tools.service import Tools

	class Answer(BaseModel):
		answer: str

	agent = Agent(
		task='Return structured answer.',
		output_model_schema=Answer,
		use_vision=False,
	)

	action_names = set(agent.tools.registry.registry.actions)
	done_schema = agent.DoneActionModel.model_json_schema()

	assert isinstance(agent.tools, Tools)
	assert 'done' in action_names
	assert 'screenshot' not in action_names
	assert agent.ActionModel is not None
	assert agent.DoneActionModel is not None
	assert agent.AgentOutput is not None
	assert 'done' in str(done_schema)


async def test_rust_agent_updates_action_models_for_page(monkeypatch):
	from browser_use.rust import Agent

	agent = Agent(task='Use page-specific tools.')
	registry = agent.tools.registry
	original_create_action_model = registry.create_action_model
	seen = []

	def recording_create_action_model(*args, **kwargs):
		seen.append(kwargs)
		return original_create_action_model(*args, **kwargs)

	monkeypatch.setattr(registry, 'create_action_model', recording_create_action_model)

	await agent._update_action_models_for_page('https://example.com/settings')

	assert seen == [
		{'page_url': 'https://example.com/settings'},
		{'include_actions': ['done'], 'page_url': 'https://example.com/settings'},
	]
	assert agent.ActionModel is not None
	assert agent.DoneActionModel is not None
	assert agent.AgentOutput is not None
	assert agent.DoneAgentOutput is not None


def test_rust_agent_initializes_runtime_metadata_and_observability():
	from browser_use.rust import Agent
	from browser_use.tokens.service import TokenCost

	class LLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	llm = LLM()
	agent = Agent(
		task='Inspect metadata.',
		llm=llm,
		task_id='task-1234',
		source='ci',
		calculate_cost=True,
		use_thinking=False,
	)

	assert agent.version
	assert agent.source == 'ci'
	assert agent.logger.name.endswith('1234 Target --')
	assert agent.eventbus is not None
	assert callable(agent.telemetry.capture)
	assert callable(agent.telemetry.flush)
	assert isinstance(agent.token_cost_service, TokenCost)
	assert agent.token_cost_service.include_cost is True
	assert str(id(llm)) in agent.token_cost_service.registered_llms
	assert agent.DoneAgentOutput is not None


def test_rust_agent_initializes_message_manager_and_followup_state():
	from browser_use.agent.message_manager.service import MessageManager
	from browser_use.rust import Agent

	agent = Agent(
		task='Initial task.',
		task_id='task-with-hyphen',
		include_recent_events=True,
	)
	initial_eventbus_name = agent.eventbus.name

	agent.add_new_task('Follow up task.')

	assert isinstance(agent.message_manager, MessageManager)
	assert agent.message_manager is agent._message_manager
	assert agent.message_manager.include_recent_events is True
	assert '<initial_user_request>' in agent.message_manager.task
	assert '<follow_up_user_request> Follow up task. </follow_up_user_request>' in agent.message_manager.task
	assert agent.state.follow_up_task is True
	assert agent.state.stopped is False
	assert agent.state.paused is False
	assert agent.eventbus.name.startswith(initial_eventbus_name)
	assert agent.eventbus.name.isidentifier()


def test_rust_agent_initializes_browser_use_session_and_file_system(tmp_path):
	from browser_use.browser import BrowserProfile, BrowserSession
	from browser_use.rust import Agent

	file_system_path = tmp_path / 'agent-files'
	downloads_path = tmp_path / 'downloads'
	agent = Agent(
		task='Open example.com',
		task_id='task-1234',
		browser_profile=BrowserProfile(headless=True, downloads_path=downloads_path),
		file_system_path=str(file_system_path),
	)

	assert isinstance(agent.browser_session, BrowserSession)
	assert agent.browser_session.id.endswith('1234')
	assert agent.browser_profile is agent.browser_session.browser_profile
	assert agent.browser_profile.downloads_path == downloads_path
	assert agent.has_downloads_path is True
	assert agent.file_system_path == str(file_system_path)
	assert agent.file_system.base_dir == file_system_path
	assert agent.state.file_system_state is not None


def test_rust_agent_browser_profile_property_tracks_session_profile():
	from browser_use.rust import Agent

	class FirstProfile:
		downloads_path = None

	class SecondProfile:
		downloads_path = '/tmp/changed-downloads'

	class BrowserSession:
		browser_profile = FirstProfile()

	session = BrowserSession()
	agent = Agent(task='Use the current browser profile.', browser_session=session)

	assert agent.browser_profile is session.browser_profile

	session.browser_profile = SecondProfile()

	assert agent.browser_profile is session.browser_profile
	assert agent.browser_profile.downloads_path == '/tmp/changed-downloads'


async def test_rust_agent_tracks_downloaded_files_and_saves_file_system_state(tmp_path):
	from browser_use.rust import Agent

	class BrowserProfile:
		downloads_path = tmp_path / 'downloads'

	class BrowserSession:
		browser_profile = BrowserProfile()
		downloaded_files = ['/tmp/report.csv', '/tmp/report.csv']

	agent = Agent(
		task='Use downloaded files.',
		browser_session=BrowserSession(),
		available_file_paths=['/tmp/input.txt'],
		file_system_path=str(tmp_path / 'agent-files'),
	)

	await agent._check_and_update_downloads('test')
	BrowserSession.downloaded_files = ['/tmp/report.csv', '/tmp/summary.pdf']
	await agent._check_and_update_downloads('test')

	agent.state.file_system_state = None
	agent.save_file_system_state()

	assert agent.available_file_paths == ['/tmp/input.txt', '/tmp/report.csv', '/tmp/summary.pdf']
	assert agent._last_known_downloads == ['/tmp/report.csv', '/tmp/summary.pdf']
	assert agent.state.file_system_state is not None
	assert agent.state.file_system_state.base_dir == str(tmp_path / 'agent-files')


async def test_rust_agent_initializes_screenshot_service(tmp_path):
	import base64

	from browser_use.rust import Agent
	from browser_use.screenshots.service import ScreenshotService

	agent = Agent(task='Capture a screenshot.', file_system_path=str(tmp_path / 'agent-files'))

	assert isinstance(agent.screenshot_service, ScreenshotService)
	assert agent.screenshot_service.agent_directory == agent.agent_directory
	assert agent.screenshot_service.screenshots_dir == agent.agent_directory / 'screenshots'
	assert agent.screenshot_service.screenshots_dir.exists()

	screenshot_b64 = base64.b64encode(b'png-bytes').decode('utf-8')
	screenshot_path = await agent.screenshot_service.store_screenshot(screenshot_b64, step_number=3)

	assert Path(screenshot_path).name == 'step_3.png'
	assert Path(screenshot_path).read_bytes() == b'png-bytes'
	assert await agent.screenshot_service.get_screenshot(screenshot_path) == screenshot_b64


def test_rust_agent_adds_available_files_to_task_context():
	from browser_use.rust import Agent

	agent = Agent(
		task='Summarize the provided report.',
		available_file_paths=['/tmp/report.txt', '~/notes.md'],
	)

	assert agent.available_file_paths == ['/tmp/report.txt', '~/notes.md']
	assert 'Available local files:' in agent.task
	assert '- /tmp/report.txt' in agent.task
	assert '- ' in agent.task and 'notes.md' in agent.task


def test_rust_agent_default_codex_model_matches_chatgpt_account(monkeypatch):
	from browser_use.rust import Agent

	monkeypatch.delenv('BROWSER_USE_RUST_MODEL', raising=False)

	assert Agent(task='report title').model == 'gpt-5.3-codex-spark'


def test_rust_agent_translates_followup_to_existing_terminal_session(monkeypatch):
	from browser_use.rust import Agent

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	agent = Agent(task='start', llm=type('LLM', (), {'model': 'gpt-test'})())
	agent.terminal_session_id = '12345678-1234-1234-1234-123456789abc'

	argv = agent._run_existing_argv(max_steps=9)

	assert argv[0] == '/tmp/browser-use-terminal'
	assert argv[-4:] == ['run-codex-session', agent.terminal_session_id, '--model', 'gpt-test']
	assert 'max_turns=9' in argv


async def test_rust_agent_keeps_browser_use_session_id_separate_from_terminal_session(monkeypatch):
	from browser_use.rust import Agent

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	agent = Agent(task='start', task_id='task-1', llm=type('LLM', (), {'model': 'gpt-test'})())
	browser_use_session_id = agent.session_id

	assert isinstance(browser_use_session_id, str)
	assert browser_use_session_id
	assert agent.terminal_session_id is None

	async def fake_run_process(argv, timeout_seconds=None):
		return 0, 'Session: 12345678-1234-1234-1234-123456789abc\n', ''

	async def fake_load_events():
		return [{'event_type': 'session.done', 'payload': {'result': 'session answer'}}]

	agent._run_process = fake_run_process
	agent._load_events = fake_load_events

	await agent.run(max_steps=1)

	assert agent.session_id == browser_use_session_id
	assert agent.terminal_session_id == '12345678-1234-1234-1234-123456789abc'
	assert agent.session_id != agent.terminal_session_id


async def test_rust_agent_invokes_browser_use_style_callbacks(monkeypatch):
	from browser_use.rust import Agent

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	seen = []

	def done_callback(history):
		seen.append(('done', history.final_result()))

	agent = Agent(task='start', llm=type('LLM', (), {'model': 'gpt-test'})(), register_done_callback=done_callback)

	async def fake_run_process(argv, timeout_seconds=None):
		assert timeout_seconds == agent.settings.step_timeout
		seen.append(('argv', argv[-4]))
		return 0, 'Session: 12345678-1234-1234-1234-123456789abc\n', ''

	async def fake_load_events():
		return [{'event_type': 'session.done', 'payload': {'result': 'ok'}}]

	async def on_step_start(callback_agent):
		seen.append(('start', callback_agent is agent))

	def on_step_end(callback_agent):
		seen.append(('end', callback_agent is agent))

	agent._run_process = fake_run_process
	agent._load_events = fake_load_events

	history = await agent.run(max_steps=3, on_step_start=on_step_start, on_step_end=on_step_end)

	assert history.final_result() == 'ok'
	assert seen == [
		('start', True),
		('argv', 'run-codex'),
		('end', True),
		('done', 'ok'),
	]


async def test_rust_agent_logs_completion_before_done_callback(monkeypatch):
	import logging

	from browser_use.rust import Agent

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	seen = []
	logged_messages = []
	original_info = logging.Logger.info

	def recording_info(logger, message, *args, **kwargs):
		logged_messages.append(str(message))
		return original_info(logger, message, *args, **kwargs)

	monkeypatch.setattr(logging.Logger, 'info', recording_info)

	def done_callback(history):
		seen.append(('done', history.final_result()))

	agent = Agent(
		task='start',
		task_id='completion-logs',
		llm=type('LLM', (), {'model': 'gpt-test'})(),
		register_done_callback=done_callback,
	)
	original_log_completion = agent.log_completion

	async def recording_log_completion():
		await original_log_completion()
		seen.append(('logged', None))

	agent.log_completion = recording_log_completion

	async def fake_run_process(argv, timeout_seconds=None):
		return 0, 'Session: 12345678-1234-1234-1234-123456789abc\n', ''

	async def fake_load_events():
		return [{'event_type': 'session.done', 'payload': {'result': 'logged answer'}}]

	agent._run_process = fake_run_process
	agent._load_events = fake_load_events

	await agent.run(max_steps=1)

	assert seen == [('logged', None), ('done', 'logged answer')]
	assert 'Task completed successfully' in logged_messages


async def test_rust_agent_generates_gif_after_done_callback(monkeypatch, tmp_path):
	from browser_use.agent import gif as gif_module
	from browser_use.rust import Agent

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	seen = []
	output_path = tmp_path / 'rust-agent.gif'

	def done_callback(history):
		seen.append(('done', history.final_result()))

	def fake_create_history_gif(task, history, output_path):
		seen.append(('gif', task, history.final_result(), output_path))

	monkeypatch.setattr(gif_module, 'create_history_gif', fake_create_history_gif)
	agent = Agent(
		task='Create a visual trace.',
		llm=type('LLM', (), {'model': 'gpt-test'})(),
		register_done_callback=done_callback,
		generate_gif=str(output_path),
	)

	async def fake_run_process(argv, timeout_seconds=None):
		return 0, 'Session: 12345678-1234-1234-1234-123456789abc\n', ''

	async def fake_load_events():
		return [{'event_type': 'session.done', 'payload': {'result': 'gif answer'}}]

	agent._run_process = fake_run_process
	agent._load_events = fake_load_events

	await agent.run(max_steps=1)

	assert seen == [
		('done', 'gif answer'),
		('gif', agent.task, 'gif answer', str(output_path)),
	]


async def test_rust_agent_invokes_new_step_callback(monkeypatch):
	from browser_use.rust import Agent

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	seen = []

	def new_step_callback(browser_state, model_output, step_number):
		seen.append((browser_state.url, model_output, step_number))

	agent = Agent(
		task='start',
		llm=type('LLM', (), {'model': 'gpt-test'})(),
		register_new_step_callback=new_step_callback,
	)

	async def fake_run_process(argv, timeout_seconds=None):
		assert timeout_seconds == agent.settings.step_timeout
		return 0, 'Session: 12345678-1234-1234-1234-123456789abc\n', ''

	async def fake_load_events():
		return [
			{'event_type': 'browser.state', 'payload': {'url': 'https://example.com', 'title': 'Example'}},
			{'event_type': 'session.done', 'payload': {'result': 'ok'}},
		]

	agent._run_process = fake_run_process
	agent._load_events = fake_load_events

	await agent.run(max_steps=3)

	assert seen == [('https://example.com', None, 2)]


def test_rust_agent_run_sync_delegates_to_async_run(monkeypatch):
	from browser_use.rust import Agent

	agent = Agent(task='start')

	async def fake_run(max_steps=100, on_step_start=None, on_step_end=None):
		agent.kwargs['seen_max_steps'] = max_steps
		return agent.history

	agent.run = fake_run

	assert agent.run_sync(max_steps=7) is agent.history
	assert agent.kwargs['seen_max_steps'] == 7


def test_rust_agent_lifecycle_state_and_save_history(tmp_path):
	from browser_use.rust import Agent
	from browser_use.rust.service import _history_from_events

	agent = Agent(task='start')
	agent.pause()
	assert agent.state.paused is True
	agent.resume()
	assert agent.state.paused is False
	agent.stop()
	assert agent.state.stopped is True

	agent.history = _history_from_events(
		[{'event_type': 'session.done', 'payload': {'result': 'saved answer'}}],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)
	history_file = tmp_path / 'history.json'
	agent.save_history(history_file)

	assert 'saved answer' in history_file.read_text(encoding='utf-8')


async def test_rust_agent_check_stop_or_pause_matches_browser_use_lifecycle():
	from browser_use.rust import Agent

	seen = []

	async def should_stop():
		seen.append('should_stop')
		return True

	agent = Agent(task='check controls', register_should_stop_callback=should_stop)

	with pytest.raises(InterruptedError):
		await agent._check_stop_or_pause()

	assert seen == ['should_stop']
	assert agent.state.stopped is True

	paused_agent = Agent(task='check pause')
	paused_agent.pause()

	with pytest.raises(InterruptedError):
		await paused_agent._check_stop_or_pause()

	assert paused_agent.state.paused is True


async def test_rust_agent_rerun_history_delegates_to_rust_run():
	from browser_use.rust import Agent
	from browser_use.rust.service import _history_from_events

	agent = Agent(task='rerun start', max_steps=8)
	previous = _history_from_events(
		[{'event_type': 'session.done', 'payload': {'result': 'previous answer'}}],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)
	seen = []

	async def fake_run(max_steps=100, on_step_start=None, on_step_end=None):
		seen.append(max_steps)
		return _history_from_events(
			[{'event_type': 'session.done', 'payload': {'result': 'rerun answer'}}],
			model='gpt-test',
			started=3.0,
			finished=4.0,
			output_model_schema=None,
			process_error=None,
		)

	agent.run = fake_run

	results = await agent.rerun_history(previous)

	assert seen == [8]
	assert len(results) == 1
	assert results[0].extracted_content == 'rerun answer'


async def test_rust_agent_load_and_rerun_loads_saved_rust_history(tmp_path):
	from browser_use.rust import Agent
	from browser_use.rust.service import _history_from_events

	agent = Agent(task='rerun saved')
	history = _history_from_events(
		[{'event_type': 'session.done', 'payload': {'result': 'loaded answer'}}],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)
	history_file = tmp_path / 'history.json'
	history.save_to_file(history_file)
	seen = []

	async def fake_rerun_history(loaded_history, **kwargs):
		seen.append((loaded_history.final_result(), kwargs))
		return loaded_history.action_results()

	agent.rerun_history = fake_rerun_history

	results = await agent.load_and_rerun(history_file, max_retries=2)

	assert seen == [('loaded answer', {'max_retries': 2})]
	assert results[0].extracted_content == 'loaded answer'


async def test_rust_agent_take_step_runs_one_terminal_turn():
	from browser_use.rust import Agent
	from browser_use.rust.service import _history_from_events

	agent = Agent(task='step once')
	seen = []

	async def fake_run(max_steps=100, on_step_start=None, on_step_end=None):
		seen.append(max_steps)
		return _history_from_events(
			[{'event_type': 'session.done', 'payload': {'result': 'single step answer'}}],
			model='gpt-test',
			started=1.0,
			finished=2.0,
			output_model_schema=None,
			process_error=None,
		)

	agent.run = fake_run

	is_done, is_valid = await agent.take_step()

	assert seen == [1]
	assert is_done is True
	assert is_valid is True


async def test_rust_agent_step_runs_single_terminal_turn_and_updates_state(monkeypatch):
	from browser_use.rust import Agent

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	agent = Agent(task='step once', llm=type('LLM', (), {'model': 'gpt-test'})())
	seen = []

	async def fake_run_process(argv, timeout_seconds=None):
		seen.append((argv, timeout_seconds))
		return 0, 'Session: 12345678-1234-1234-1234-123456789abc\n', ''

	async def fake_load_events():
		return [
			{'event_type': 'browser.state', 'payload': {'url': 'https://example.com', 'title': 'Example'}},
			{'event_type': 'session.done', 'payload': {'result': 'step answer'}},
		]

	agent._run_process = fake_run_process
	agent._load_events = fake_load_events

	result = await agent.step()

	assert result is None
	assert len(seen) == 1
	assert seen[0][0][0] == '/tmp/browser-use-terminal'
	assert 'max_turns=1' in seen[0][0]
	assert seen[0][1] == agent.settings.step_timeout
	assert agent.history.final_result() == 'step answer'
	assert agent.state.last_result is not None
	assert agent.state.last_result[-1].is_done is True
	assert agent.state.last_result[-1].extracted_content == 'step answer'


async def test_rust_agent_execute_step_runs_one_turn_with_callbacks(monkeypatch):
	from browser_use.agent.views import AgentStepInfo
	from browser_use.rust import Agent

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	seen = []

	def done_callback(history):
		seen.append(('done', history.final_result()))

	agent = Agent(
		task='execute one step',
		llm=type('LLM', (), {'model': 'gpt-test'})(),
		register_done_callback=done_callback,
	)

	async def fake_run_process(argv, timeout_seconds=None):
		seen.append(('argv', argv[-4], timeout_seconds))
		return 0, 'Session: 12345678-1234-1234-1234-123456789abc\n', ''

	async def fake_load_events():
		return [{'event_type': 'session.done', 'payload': {'result': 'execute step answer'}}]

	async def on_step_start(callback_agent):
		seen.append(('start', callback_agent is agent))

	def on_step_end(callback_agent):
		seen.append(('end', callback_agent is agent))

	agent._run_process = fake_run_process
	agent._load_events = fake_load_events

	is_done = await agent._execute_step(
		step=0,
		max_steps=1,
		step_info=AgentStepInfo(step_number=0, max_steps=1),
		on_step_start=on_step_start,
		on_step_end=on_step_end,
	)

	assert is_done is True
	assert seen == [
		('start', True),
		('argv', 'run-codex', agent.settings.step_timeout),
		('end', True),
		('done', 'execute step answer'),
	]


async def test_rust_agent_multi_act_preserves_done_action():
	from browser_use.rust import Agent

	agent = Agent(task='finish manually')

	results = await agent.multi_act([{'done': {'text': 'manual answer', 'success': False, 'files_to_display': ['report.txt']}}])

	assert len(results) == 1
	assert results[0].is_done is True
	assert results[0].success is False
	assert results[0].extracted_content == 'manual answer'
	assert results[0].attachments == ['report.txt']


async def test_rust_agent_multi_act_routes_actions_to_followup():
	from browser_use.rust import Agent
	from browser_use.rust.service import _history_from_events

	agent = Agent(task='act on current page')
	agent.terminal_session_id = '12345678-1234-1234-1234-123456789abc'
	seen = []

	async def fake_follow_up(task, max_steps=None):
		seen.append((task, max_steps))
		return _history_from_events(
			[{'event_type': 'session.done', 'payload': {'result': 'actions applied'}}],
			model='gpt-test',
			started=1.0,
			finished=2.0,
			output_model_schema=None,
			process_error=None,
		)

	agent.follow_up = fake_follow_up

	results = await agent.multi_act(
		[
			{'click_element': {'index': 2}},
			{'input_text': {'index': 3, 'text': 'hello'}},
		]
	)

	assert seen[0][1] == 2
	assert 'Browser Use action models' in seen[0][0]
	assert '"click_element"' in seen[0][0]
	assert '"input_text"' in seen[0][0]
	assert results[0].extracted_content == 'actions applied'


async def test_rust_agent_trace_and_cloud_auth_helpers():
	from browser_use.rust import Agent
	from browser_use.rust.service import _history_from_events

	agent = Agent(task='Open example.com', llm=type('LLM', (), {'model': 'gpt-test'})(), task_id='task-1')
	agent.history = _history_from_events(
		[
			{'event_type': 'browser.state', 'payload': {'url': 'https://example.com', 'title': 'Example'}},
			{'event_type': 'session.done', 'payload': {'result': 'trace answer'}},
		],
		model='gpt-test',
		started=1.0,
		finished=3.0,
		output_model_schema=None,
		process_error=None,
	)

	trace_object = agent.get_trace_object()

	assert await agent.authenticate_cloud_sync() is False
	assert set(trace_object) == {'trace', 'trace_details'}
	assert trace_object['trace']['model'] == 'gpt-test'
	assert trace_object['trace']['task_id'] == 'task-1'
	assert trace_object['trace']['final_result_response_truncated'] == 'trace answer'
	assert trace_object['trace']['self_report_completed'] == 1
	assert trace_object['trace_details']['final_result_response'] == 'trace answer'
	assert 'trace answer' in trace_object['trace_details']['complete_history']


async def test_rust_agent_saves_terminal_conversation(tmp_path, monkeypatch):
	from browser_use.rust import Agent

	monkeypatch.setenv('BROWSER_USE_TERMINAL_BINARY', '/tmp/browser-use-terminal')
	agent = Agent(
		task='start',
		llm=type('LLM', (), {'model': 'gpt-test'})(),
		task_id='task-1',
		save_conversation_path=tmp_path,
	)

	async def fake_run_process(argv, timeout_seconds=None):
		assert timeout_seconds == agent.settings.step_timeout
		return 0, 'Session: 12345678-1234-1234-1234-123456789abc\n', ''

	async def fake_load_events():
		return [
			{'event_type': 'browser.state', 'payload': {'url': 'https://example.com', 'title': 'Example'}},
			{'event_type': 'session.done', 'payload': {'result': 'saved transcript'}},
		]

	agent._run_process = fake_run_process
	agent._load_events = fake_load_events

	await agent.run(max_steps=3)
	files = list(tmp_path.glob('conversation_task-1_*.json'))

	assert len(files) == 1
	snapshot = json.loads(files[0].read_text(encoding='utf-8'))
	assert snapshot['task_id'] == 'task-1'
	assert snapshot['session_id'] == agent.session_id
	assert snapshot['terminal_session_id'] == '12345678-1234-1234-1234-123456789abc'
	assert snapshot['final_result'] == 'saved transcript'
	assert snapshot['events'][0]['event_type'] == 'browser.state'
	assert agent.state.n_steps == 2


async def test_rust_agent_terminal_process_timeout():
	from browser_use.rust import Agent

	agent = Agent(task='slow', step_timeout=1)

	returncode, stdout, stderr = await agent._run_process(
		[sys.executable, '-c', 'import time; time.sleep(5)'],
		timeout_seconds=0.01,
	)

	assert returncode == 124
	assert stdout == ''
	assert 'timed out after 0.01 seconds' in stderr


def test_rust_history_marks_process_failure_not_done():
	from browser_use.rust.service import _history_from_events

	history = _history_from_events(
		[],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error='terminal failed',
	)

	assert history.final_result() is None
	assert history.is_done() is False
	assert history.is_successful() is None
	assert history.errors() == ['terminal failed']


def test_rust_history_marks_missing_terminal_result_as_error():
	from browser_use.rust.service import _history_from_events

	history = _history_from_events(
		[{'event_type': 'model.turn.request', 'payload': {'model': 'gpt-test'}}],
		model='gpt-test',
		started=1.0,
		finished=2.0,
		output_model_schema=None,
		process_error=None,
	)

	assert history.final_result() is None
	assert history.is_done() is False
	assert history.errors() == ['Rust terminal session did not produce a final result.']


def test_real_v8_smoke_selects_case_by_index_and_task_id(tmp_path):
	module = _load_real_v8_smoke_module()
	dataset = tmp_path / 'real_v8.json'
	dataset.write_text(
		json.dumps(
			[
				{'task_id': '1', 'confirmed_task': 'first task'},
				{'task_id': '2', 'confirmed_task': 'second task'},
			]
		),
		encoding='utf-8',
	)

	cases = module.load_cases(dataset)

	assert module.select_case(cases, index=1, task_id=None)['confirmed_task'] == 'second task'
	assert module.select_case(cases, index=None, task_id='1')['confirmed_task'] == 'first task'
	with pytest.raises(ValueError, match='Select by index or task_id'):
		module.select_case(cases, index=0, task_id='1')
