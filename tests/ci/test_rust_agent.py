from __future__ import annotations

import inspect
import importlib.util
import json
import sys
from pathlib import Path
from typing import get_args, get_origin, get_type_hints

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


def test_agent_service_export_uses_rust_wrapper():
	from browser_use.agent.service import Agent as ServiceAgent
	from browser_use.rust import Agent as RustAgent

	assert ServiceAgent is RustAgent


def test_rust_agent_generic_subscription_matches_browser_use():
	from browser_use.agent.service import Agent as ServiceAgent
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.rust import Agent as RustAgent

	class Answer(BaseModel):
		answer: str

	browser_use_alias = BrowserUseAgent[dict, Answer]
	rust_alias = RustAgent[dict, Answer]
	service_alias = ServiceAgent[dict, Answer]

	assert get_args(rust_alias) == get_args(browser_use_alias) == (dict, Answer)
	assert get_args(service_alias) == (dict, Answer)
	assert get_origin(rust_alias) is RustAgent
	assert get_origin(service_alias) is RustAgent

	with pytest.raises(TypeError, match='Too few arguments'):
		RustAgent[Answer]


def test_rust_agent_constructor_signature_matches_browser_use_order(tmp_path):
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.rust import Agent as RustAgent

	browser_use_params = list(inspect.signature(BrowserUseAgent.__init__).parameters)
	rust_params = list(inspect.signature(RustAgent.__init__).parameters)

	assert rust_params == browser_use_params

	values = []
	for param in list(inspect.signature(RustAgent.__init__).parameters.values())[1:]:
		if param.name == 'task':
			values.append('Check constructor parity.')
		elif param.name == 'source':
			values.append('signature-source')
		elif param.name == 'file_system_path':
			values.append(str(tmp_path / 'agent-files'))
		elif param.name == 'task_id':
			values.append('signature-task-id')
			break
		else:
			assert param.default is not inspect.Parameter.empty
			values.append(param.default)

	agent = RustAgent(*values)

	assert agent.source == 'signature-source'
	assert agent.file_system_path == str(tmp_path / 'agent-files')
	assert agent.task_id == 'signature-task-id'


def test_rust_agent_constructor_type_hints_match_browser_use_core_params():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.rust import Agent as RustAgent
	from browser_use.tools.service import Tools

	browser_use_hints = get_type_hints(BrowserUseAgent.__init__)
	rust_hints = get_type_hints(RustAgent.__init__)

	for name in (
		'llm',
		'register_new_step_callback',
		'register_done_callback',
		'output_model_schema',
		'page_extraction_llm',
		'sample_images',
	):
		assert rust_hints[name] == browser_use_hints[name]

	def assert_tools_context_hint(annotation):
		inner = [arg for arg in get_args(annotation) if arg is not type(None)]
		assert len(inner) == 1
		assert get_origin(inner[0]) is Tools
		type_args = get_args(inner[0])
		assert len(type_args) == 1
		assert type_args[0].__name__ == 'Context'

	for name in ('tools', 'controller'):
		assert_tools_context_hint(browser_use_hints[name])
		assert_tools_context_hint(rust_hints[name])

	assert 'kwargs' not in rust_hints
	assert 'return' not in rust_hints


def test_rust_agent_run_type_hints_match_browser_use_hooks():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.rust import Agent as RustAgent

	for method_name in ('run', 'run_sync'):
		browser_use_hints = get_type_hints(getattr(BrowserUseAgent, method_name))
		rust_hints = get_type_hints(getattr(RustAgent, method_name))

		assert rust_hints == browser_use_hints


def test_rust_agent_action_model_helper_type_hints_match_browser_use():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.rust import Agent as RustAgent

	for method_name in ('_convert_initial_actions', '_update_action_indices', 'multi_act'):
		browser_use_hints = get_type_hints(getattr(BrowserUseAgent, method_name))
		rust_hints = get_type_hints(getattr(RustAgent, method_name))

		assert rust_hints == browser_use_hints


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


def test_rust_agent_exposes_url_text_helper_methods():
	from browser_use.llm.messages import ContentPartTextParam, UserMessage
	from browser_use.rust import Agent

	class Nested(BaseModel):
		url: str

	class Restored(BaseModel):
		text: str
		nested: Nested
		items: list
		pair: tuple[str, str]

	agent = Agent(task='Shorten URLs.', _url_shortening_limit=8)
	original_url = 'https://example.com/path?abcdefghijklmnopqrstuvwxyz#section'
	text = f'Open {original_url} now.'

	cleaned = agent._remove_think_tags('visible <think>hidden</think> answer')
	shortened_text, replacements = agent._replace_urls_in_text(text)
	shortened_url = next(iter(replacements))
	message = UserMessage(content=[ContentPartTextParam(text=text)])
	message_replacements = agent._process_messsages_and_replace_long_urls_shorter_ones([message])
	model = Restored(
		text=shortened_url,
		nested=Nested(url=shortened_url),
		items=[shortened_url, {'url': shortened_url}],
		pair=(shortened_url, 'untouched'),
	)

	Agent._recursive_process_all_strings_inside_pydantic_model(model, replacements)

	assert cleaned == 'visible  answer'
	assert original_url not in shortened_text
	assert replacements[shortened_url] == original_url
	assert Agent._replace_shortened_urls_in_string(shortened_text, replacements) == text
	assert message_replacements
	assert original_url not in message.content[0].text
	assert model.text == original_url
	assert model.nested.url == original_url
	assert model.items == [original_url, {'url': original_url}]
	assert model.pair == (original_url, 'untouched')


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


def test_rust_agent_defaults_page_extraction_llm_to_main_llm():
	from browser_use.rust import Agent

	class LLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	class ExtractionLLM:
		model = 'extract-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	llm = LLM()
	extraction_llm = ExtractionLLM()

	default_agent = Agent(task='Extract with the main model.', llm=llm)
	override_agent = Agent(
		task='Extract with a dedicated model.',
		llm=llm,
		page_extraction_llm=extraction_llm,
	)

	assert default_agent.settings.page_extraction_llm is llm
	assert override_agent.settings.page_extraction_llm is extraction_llm
	assert str(id(llm)) in default_agent.token_cost_service.registered_llms
	assert str(id(extraction_llm)) in override_agent.token_cost_service.registered_llms


def test_rust_agent_enables_flash_mode_for_browser_use_llm_provider():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.rust import Agent as RustAgent

	class BrowserUseLLM:
		model = 'browser-use-test'
		provider = 'browser-use'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	class OtherLLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	browser_use_llm = BrowserUseLLM()
	browser_use_agent = BrowserUseAgent(task='Use Browser Use model.', llm=browser_use_llm, directly_open_url=False)
	rust_browser_use_agent = RustAgent(task='Use Browser Use model.', llm=browser_use_llm, directly_open_url=False)
	rust_other_agent = RustAgent(task='Use another model.', llm=OtherLLM(), directly_open_url=False)

	assert browser_use_agent.settings.flash_mode is True
	assert rust_browser_use_agent.settings.flash_mode is True
	assert rust_other_agent.settings.flash_mode is False
	assert rust_browser_use_agent.AgentOutput.__name__ == browser_use_agent.AgentOutput.__name__


def test_rust_agent_llm_timeout_defaults_match_browser_use_model_families():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.rust import Agent as RustAgent

	class LLM:
		provider = 'test'

		def __init__(self, model):
			self.model = model

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	for model in ['gpt-test', 'gemini-2.5-pro', 'groq-llama', 'o3-mini', 'claude-sonnet', 'deepseek-chat']:
		browser_use_agent = BrowserUseAgent(task='Inspect timeout.', llm=LLM(model), directly_open_url=False)
		rust_agent = RustAgent(task='Inspect timeout.', llm=LLM(model), directly_open_url=False)

		assert rust_agent.settings.llm_timeout == browser_use_agent.settings.llm_timeout

	override_agent = RustAgent(task='Override timeout.', llm=LLM('gemini-2.5-pro'), llm_timeout=12)

	assert override_agent.settings.llm_timeout == 12


def test_rust_agent_disables_vision_for_unsupported_model_families():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.rust import Agent as RustAgent

	class LLM:
		provider = 'test'

		def __init__(self, model):
			self.model = model

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	for model in ['deepseek-chat', 'grok-2', 'xai-grok']:
		browser_use_agent = BrowserUseAgent(task='Inspect vision.', llm=LLM(model), directly_open_url=False, use_vision=True)
		rust_agent = RustAgent(task='Inspect vision.', llm=LLM(model), directly_open_url=False, use_vision=True)

		assert browser_use_agent.settings.use_vision is False
		assert rust_agent.settings.use_vision is False

	normal_agent = RustAgent(task='Inspect vision.', llm=LLM('gpt-test'), directly_open_url=False, use_vision=True)

	assert normal_agent.settings.use_vision is True


def test_rust_agent_state_id_defaults_like_browser_use():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.agent.views import AgentState
	from browser_use.rust import Agent as RustAgent

	class LLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	llm = LLM()
	browser_use_task_id = 'browser_use_state'
	rust_task_id = 'rust_state_id'
	browser_use_agent = BrowserUseAgent(
		task='Inspect state.',
		llm=llm,
		task_id=browser_use_task_id,
		directly_open_url=False,
	)
	rust_agent = RustAgent(task='Inspect state.', llm=llm, task_id=rust_task_id, directly_open_url=False)

	assert browser_use_agent.task_id == browser_use_task_id
	assert rust_agent.task_id == rust_task_id
	assert browser_use_agent.state.agent_id != browser_use_task_id
	assert rust_agent.state.agent_id != rust_task_id
	assert rust_agent.state.n_steps == browser_use_agent.state.n_steps == 1

	injected_state = AgentState(agent_id='restored-state-id')
	restored_agent = RustAgent(task='Restore state.', injected_agent_state=injected_state)

	assert restored_agent.state is injected_state
	assert restored_agent.state.agent_id == 'restored-state-id'


def test_rust_agent_eventbus_name_matches_browser_use_suffix_prefix():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.rust import Agent as RustAgent

	class LLM:
		model = 'gpt-test'
		provider = 'test'

		async def ainvoke(self, messages, output_format=None, **kwargs):
			return type('Result', (), {'usage': None})()

	browser_use_agent = BrowserUseAgent(task='Inspect event bus.', llm=LLM(), task_id='browseruseabcd', directly_open_url=False)
	rust_agent = RustAgent(task='Inspect event bus.', llm=LLM(), task_id='rustagentwxyz', directly_open_url=False)

	assert browser_use_agent.eventbus.name == 'Agent_abcd'
	assert rust_agent.eventbus.name == 'Agent_wxyz'

	rust_agent_with_hyphen = RustAgent(task='Inspect event bus.', llm=LLM(), task_id='task-1', directly_open_url=False)
	initial_name = rust_agent_with_hyphen.eventbus.name
	rust_agent_with_hyphen.add_new_task('Follow up.')

	assert initial_name == 'Agent_sk_1'
	assert rust_agent_with_hyphen.eventbus.name.startswith(f'{initial_name}_')
	assert rust_agent_with_hyphen.eventbus.name.isidentifier()


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


def test_rust_agent_setup_action_models_signature_matches_browser_use():
	from browser_use.agent.service import _PythonAgent as BrowserUseAgent
	from browser_use.rust import Agent as RustAgent

	browser_use_signature = inspect.signature(BrowserUseAgent._setup_action_models)
	rust_signature = inspect.signature(RustAgent._setup_action_models)

	assert list(rust_signature.parameters) == list(browser_use_signature.parameters) == ['self']

	agent = RustAgent(task='Rebuild action models.')
	agent.ActionModel = None
	agent.DoneActionModel = None
	agent.AgentOutput = None
	agent.DoneAgentOutput = None

	agent._setup_action_models()

	assert agent.ActionModel is not None
	assert agent.DoneActionModel is not None
	assert agent.AgentOutput is not None
	assert agent.DoneAgentOutput is not None


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


async def test_rust_agent_exposes_logging_helper_methods(monkeypatch):
	import time

	import browser_use.rust.service as rust_service
	from browser_use.agent.views import ActionResult
	from browser_use.rust import Agent

	class LLM:
		model = 'gpt-test'
		provider = 'test-provider'

	class BrowserProfile:
		downloads_path = None

	class BrowserSession:
		cdp_url = 'wss://browser.example/devtools/browser/1'
		browser_profile = BrowserProfile()

	class FakeAction:
		def model_dump(self, **kwargs):
			return {'navigate': {'url': 'https://example.com', 'new_tab': False}}

	class Parsed:
		action = [FakeAction()]

	class DomState:
		selector_map = {1: object(), 2: object()}

	class BrowserStateSummary:
		url = 'https://example.com/a/very/long/path/that/will/be/shortened/in/logging'
		dom_state = DomState()

	async def no_latest_version():
		return None

	captured_events = []

	class Telemetry:
		def capture(self, event):
			captured_events.append(event)

	monkeypatch.setattr(rust_service, 'check_latest_browser_use_version', no_latest_version)
	agent = Agent(task='Log helper parity.', llm=LLM(), browser_session=BrowserSession())
	agent.telemetry = Telemetry()

	await agent._log_agent_run()
	agent._log_first_step_startup()
	agent._log_step_context(BrowserStateSummary())
	agent._log_next_action_summary(Parsed())
	agent._log_step_completion_summary(time.time() - 1, [ActionResult(extracted_content='ok')])
	agent._log_action(FakeAction(), 'navigate', 1, 2)
	agent.history = rust_service._history_from_events(
		[
			{'event_type': 'browser.state', 'payload': {'url': 'https://example.com', 'title': 'Example'}},
			{
				'event_type': 'model.usage',
				'payload': {'input_tokens': 11, 'cached_input_tokens': 3, 'output_tokens': 7, 'cost_usd': 0.12},
			},
			{'event_type': 'session.done', 'payload': {'result': 'done'}},
		],
		model='gpt-test',
		started=1.0,
		finished=2.5,
		output_model_schema=None,
		process_error=None,
	)
	agent._sync_state_from_history()
	agent._log_final_outcome_messages()
	agent._log_agent_event(max_steps=9, agent_run_error='manual-error')

	assert captured_events
	assert captured_events[0].model == 'gpt-test'
	assert captured_events[0].model_provider == 'test-provider'
	assert captured_events[0].cdp_url == 'browser.example'
	assert captured_events[0].action_history == [None]
	assert captured_events[0].urls_visited == ['https://example.com']
	assert captured_events[0].total_input_tokens == 11
	assert captured_events[0].total_output_tokens == 7
	assert captured_events[0].prompt_cached_tokens == 3
	assert captured_events[0].final_result_response == '"done"'
	assert captured_events[0].error_message == 'manual-error'


async def test_rust_agent_exposes_step_finalization_helper_methods(tmp_path):
	import base64
	import time

	from browser_use.agent.views import ActionResult, AgentStepInfo
	from browser_use.rust import Agent

	class DomState:
		selector_map = {}

	class BrowserStateSummary:
		url = 'https://example.com/final'
		title = 'Final'
		tabs = []
		screenshot = base64.b64encode(b'png-bytes').decode('utf-8')
		dom_state = DomState()

	agent = Agent(task='Finalize helper parity.', file_system_path=str(tmp_path / 'agent-files'))

	await agent._handle_step_error(ValueError('bad step'))
	assert agent.state.consecutive_failures == 1
	assert agent.state.last_result is not None
	assert agent.state.last_result[-1].error == 'bad step'

	await agent._post_process()
	assert agent.state.consecutive_failures == 2

	agent.state.last_result = [
		ActionResult(is_done=True, success=True, extracted_content='final answer', attachments=['file:///tmp/report.txt'])
	]
	await agent._post_process()
	assert agent.state.consecutive_failures == 0

	agent.step_start_time = time.time() - 0.1
	await agent._finalize(BrowserStateSummary())

	assert agent.state.n_steps == 2
	assert agent.state.file_system_state is not None
	assert agent.history.final_result() == 'final answer'
	assert agent.history.urls() == ['https://example.com/final']
	assert Path(agent.history.history[0].state.screenshot_path).read_bytes() == b'png-bytes'

	await agent._force_done_after_last_step(AgentStepInfo(step_number=2, max_steps=3))
	assert agent.AgentOutput is agent.DoneAgentOutput

	agent.state.consecutive_failures = agent.settings.max_failures
	agent.AgentOutput = None
	await agent._force_done_after_failure()
	assert agent.AgentOutput is agent.DoneAgentOutput


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


def test_rust_agent_exposes_setup_helper_methods(tmp_path):
	from browser_use.rust import Agent
	from browser_use.screenshots.service import ScreenshotService

	class LLM:
		_verified_api_keys = True

	initial_file_system_path = tmp_path / 'initial-files'
	new_file_system_path = tmp_path / 'new-files'
	agent = Agent(
		task='Set up helpers.',
		llm=LLM(),
		file_system_path=str(initial_file_system_path),
		source='constructor-source',
	)

	agent.file_system = None
	agent.file_system_path = None
	agent._set_file_system()
	agent._set_screenshot_service()
	agent._set_browser_use_version_and_source('helper-source')

	assert agent.file_system_path == str(initial_file_system_path)
	assert agent.file_system.base_dir == initial_file_system_path
	assert isinstance(agent.screenshot_service, ScreenshotService)
	assert agent.screenshot_service.agent_directory == agent.agent_directory
	assert agent.source == 'helper-source'
	assert agent.version
	assert agent._verify_and_setup_llm() is True

	with pytest.raises(ValueError, match='Cannot provide both file_system_state'):
		agent._set_file_system(str(new_file_system_path))

	agent.state.file_system_state = None
	agent._set_file_system(str(new_file_system_path))

	assert agent.file_system_path == str(new_file_system_path)
	assert agent.file_system.base_dir == new_file_system_path


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


async def test_rust_agent_exposes_action_replay_helper_methods():
	from types import SimpleNamespace

	from browser_use.agent.views import ActionResult
	from browser_use.rust import Agent

	class BrowserProfile:
		downloads_path = None

	class BrowserSession:
		browser_profile = BrowserProfile()

		async def get_browser_state_summary(self, include_screenshot=False):
			assert include_screenshot is False
			return SimpleNamespace(
				dom_state=SimpleNamespace(selector_map={7: SimpleNamespace(element_hash='matching-hash')})
			)

	class FakeAction:
		def __init__(self):
			self.index = 2

		def get_index(self):
			return self.index

		def set_index(self, index):
			self.index = index

		def model_dump(self, **kwargs):
			return {'click_element': {'index': self.index}}

	agent = Agent(
		task='Replay actions.',
		browser_session=BrowserSession(),
		initial_actions=[{'navigate': {'url': 'https://example.com', 'new_tab': False}}],
	)
	agent.initial_url = 'https://example.com'
	initial_calls = []

	async def fake_initial_multi_act(actions):
		initial_calls.append(actions)
		return [ActionResult(long_term_memory='loaded')]

	agent.multi_act = fake_initial_multi_act
	await agent._execute_initial_actions()

	assert initial_calls == [agent.initial_actions]
	assert agent.state.last_result[0].long_term_memory == 'Found initial url and automatically loaded it. loaded'
	assert agent.history.history[0].metadata.step_number == 0
	assert agent.history.history[0].state.url == 'https://example.com'
	assert agent.history.history[0].model_output.action == agent.initial_actions

	action = FakeAction()
	replay_calls = []

	async def fake_replay_multi_act(actions):
		replay_calls.append(actions)
		return [ActionResult(extracted_content='replayed')]

	agent.multi_act = fake_replay_multi_act
	history_item = SimpleNamespace(
		model_output=SimpleNamespace(action=[action]),
		state=SimpleNamespace(interacted_element=[SimpleNamespace(element_hash='matching-hash')]),
	)
	results = await agent._execute_history_step(history_item, delay=0)

	assert action.index == 7
	assert replay_calls == [[action]]
	assert results[0].extracted_content == 'replayed'
	assert await agent._update_action_indices(
		SimpleNamespace(element_hash='missing-hash'),
		FakeAction(),
		SimpleNamespace(dom_state=SimpleNamespace(selector_map={1: SimpleNamespace(element_hash='other-hash')})),
	) is None


async def test_rust_agent_exposes_model_output_helper_methods(tmp_path):
	from types import SimpleNamespace

	from browser_use.agent.views import ActionResult
	from browser_use.llm.messages import UserMessage
	from browser_use.rust import Agent

	original_url = 'https://example.com/path?abcdefghijklmnopqrstuvwxyz#section'

	class LLM:
		model = 'gpt-test'
		provider = 'test-provider'

		def __init__(self):
			self.agent = None
			self.calls = []

		async def ainvoke(self, messages, output_format=None, **kwargs):
			self.calls.append((messages, output_format))
			shortened_text = messages[0].content
			return SimpleNamespace(
				usage=None,
				completion=self.agent.AgentOutput(
					evaluation_previous_goal='ok',
					memory='remember',
					next_goal='finish',
					action=[
						self.agent.ActionModel(done={'text': shortened_text, 'success': True}),
						self.agent.ActionModel(done={'text': 'extra action', 'success': True}),
					],
				)
			)

	seen_callbacks = []

	async def new_step_callback(browser_state, model_output, step_number):
		seen_callbacks.append((browser_state, model_output, step_number))

	llm = LLM()
	agent = Agent(
		task='Use LLM helpers.',
		llm=llm,
		max_actions_per_step=1,
		_url_shortening_limit=8,
		save_conversation_path=tmp_path / 'conversations',
		register_new_step_callback=new_step_callback,
	)
	llm.agent = agent
	input_messages = [UserMessage(content=f'Open {original_url} now.')]
	browser_state = SimpleNamespace(url='https://example.com')
	agent._message_manager.get_messages = lambda: input_messages

	await agent._get_next_action(browser_state)

	assert llm.calls[0][1] is agent.AgentOutput
	assert original_url not in llm.calls[0][0][0].content
	assert len(agent.state.last_model_output.action) == 1
	assert agent.state.last_model_output.action[0].model_dump(exclude_unset=True)['done']['text'] == f'Open {original_url} now.'
	assert seen_callbacks == [(browser_state, agent.state.last_model_output, agent.state.n_steps)]
	assert list((tmp_path / 'conversations').glob(f'conversation_{agent.id}_{agent.state.n_steps}.txt'))

	seen_actions = []

	async def fake_multi_act(actions):
		seen_actions.append(actions)
		return [ActionResult(extracted_content='executed')]

	agent.multi_act = fake_multi_act
	await agent._execute_actions()

	assert seen_actions == [agent.state.last_model_output.action]
	assert agent.state.last_result[0].extracted_content == 'executed'

	class RetryLLM(LLM):
		async def ainvoke(self, messages, output_format=None, **kwargs):
			self.calls.append((messages, output_format))
			if len(self.calls) == 1:
				return SimpleNamespace(
					usage=None,
					completion=self.agent.AgentOutput(
						evaluation_previous_goal='empty',
						memory='none',
						next_goal='retry',
						action=[],
					)
				)
			return SimpleNamespace(
				usage=None,
				completion=self.agent.AgentOutput(
					evaluation_previous_goal='ok',
					memory='remember',
					next_goal='finish',
					action=[self.agent.ActionModel(done={'text': 'retried action', 'success': True})],
				)
			)

	retry_llm = RetryLLM()
	retry_agent = Agent(task='Retry LLM helpers.', llm=retry_llm)
	retry_llm.agent = retry_agent
	retry_output = await retry_agent._get_model_output_with_retry([UserMessage(content='Retry with an action.')])

	assert len(retry_llm.calls) == 2
	assert retry_output.action


async def test_rust_agent_exposes_prepare_context_helper_method(monkeypatch):
	from types import SimpleNamespace

	from browser_use.agent.views import AgentStepInfo
	from browser_use.rust import Agent

	state_requests = []
	browser_state = SimpleNamespace(
		url='https://example.com/settings',
		title='Settings',
		screenshot='base64-screen',
		dom_state=SimpleNamespace(selector_map={1: object(), 2: object()}),
	)

	class BrowserProfile:
		downloads_path = None

	class BrowserSession:
		browser_profile = BrowserProfile()

		async def get_browser_state_summary(self, include_screenshot=False, include_recent_events=False):
			state_requests.append((include_screenshot, include_recent_events))
			return browser_state

	agent = Agent(
		task='Prepare context.',
		browser_session=BrowserSession(),
		include_recent_events=True,
		use_vision=False,
		available_file_paths=['/tmp/input.txt'],
		sensitive_data={'api_key': 'secret-value'},
	)
	download_contexts = []
	updated_pages = []
	prompt_urls = []
	created_messages = []

	async def fake_check_downloads(context=''):
		download_contexts.append(context)

	async def fake_update_action_models(page_url):
		updated_pages.append(page_url)

	def fake_prompt_description(page_url):
		prompt_urls.append(page_url)
		return 'filtered action prompt'

	def fake_create_state_messages(**kwargs):
		created_messages.append(kwargs)

	monkeypatch.setattr(agent, '_check_and_update_downloads', fake_check_downloads)
	monkeypatch.setattr(agent, '_update_action_models_for_page', fake_update_action_models)
	monkeypatch.setattr(agent.tools.registry, 'get_prompt_description', fake_prompt_description)
	monkeypatch.setattr(agent._message_manager, 'create_state_messages', fake_create_state_messages)

	step_info = AgentStepInfo(step_number=2, max_steps=3)
	result = await agent._prepare_context(step_info)

	assert result is browser_state
	assert state_requests == [(True, True)]
	assert download_contexts == ['Step 1: after getting browser state']
	assert updated_pages == ['https://example.com/settings']
	assert prompt_urls == ['https://example.com/settings']
	assert created_messages == [
		{
			'browser_state_summary': browser_state,
			'model_output': agent.state.last_model_output,
			'result': agent.state.last_result,
			'step_info': step_info,
			'use_vision': False,
			'page_filtered_actions': 'filtered action prompt',
			'sensitive_data': {'api_key': 'secret-value'},
			'available_file_paths': ['/tmp/input.txt'],
		}
	]
	assert agent.AgentOutput is agent.DoneAgentOutput


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
