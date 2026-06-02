from __future__ import annotations

from pydantic import BaseModel


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
	assert 'browser_mode="managed-headless"' in argv
	assert "First navigate to 'https://example.com'" in agent.task
	assert env['BU_CDP_URL'] == 'wss://browser.example/devtools/browser/1'


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

