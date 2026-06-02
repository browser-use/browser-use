from __future__ import annotations

import importlib.util
import json
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

	async def fake_run_process(argv):
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
