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


def test_rust_agent_adds_browser_profile_domain_constraints():
	from browser_use.rust import Agent

	class BrowserProfile:
		allowed_domains = ['example.com', '*.browser-use.com']
		prohibited_domains = {'ads.example.com'}

	agent = Agent(task='Open the allowed site.', browser_profile=BrowserProfile())

	assert agent.allowed_domains == ['example.com', '*.browser-use.com']
	assert agent.prohibited_domains == ['ads.example.com']
	assert 'Browser profile navigation constraints:' in agent.task
	assert 'Allowed domains:' in agent.task
	assert '- example.com' in agent.task
	assert '- *.browser-use.com' in agent.task
	assert 'Prohibited domains:' in agent.task
	assert '- ads.example.com' in agent.task


def test_rust_agent_mirrors_direct_url_startup():
	from browser_use.rust import Agent

	agent = Agent(task='Open example.com and report the title.')

	assert agent.initial_url == 'https://example.com'
	assert agent.initial_actions == [{'navigate': {'url': 'https://example.com', 'new_tab': False}}]
	assert "First navigate to 'https://example.com'" in agent.task


def test_rust_agent_preserves_ordered_initial_actions_context():
	from browser_use.rust import Agent

	agent = Agent(
		task='Report what is visible after setup.',
		initial_actions=[
			{'navigate': {'url': 'https://example.com', 'new_tab': False}},
			{'click_element_by_index': {'index': 3}},
		],
	)

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
	agent.session_id = '12345678-1234-1234-1234-123456789abc'

	argv = agent._run_existing_argv(max_steps=9)

	assert argv[0] == '/tmp/browser-use-terminal'
	assert argv[-4:] == ['run-codex-session', agent.session_id, '--model', 'gpt-test']
	assert 'max_turns=9' in argv


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
	assert snapshot['session_id'] == '12345678-1234-1234-1234-123456789abc'
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
