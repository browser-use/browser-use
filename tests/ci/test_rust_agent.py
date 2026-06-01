"""
Unit + integration tests for `browser_use.rust`.

The Agent surface is intentionally minimal: provider/model/api_key flow
from the `llm` object; browser config flows from the `browser` object.
There is no separate options struct.
"""

from __future__ import annotations

import asyncio
import json
import warnings

import pytest
from pydantic import BaseModel

from browser_use.rust import Agent, Provider, parse_event
from browser_use.rust.events import RawEvent, SessionInput, SessionResult
from browser_use.rust.runner import ButNotInstalledError, find_browser_use_terminal_binary
from browser_use.rust.service import _AgentSessionState

# ---------------------------------------------------------------------------
# llm/browser introspection (the entire user-facing surface)
# ---------------------------------------------------------------------------


class _FakeChat:
	def __init__(self, model: str | None = None, api_key: str | None = None):
		self.model = model
		self.api_key = api_key


def _llm_class(name: str) -> type[_FakeChat]:
	return type(name, (_FakeChat,), {})


@pytest.mark.parametrize(
	('class_name', 'expected'),
	[
		('ChatOpenAI', Provider.OPENAI),
		('ChatAzureOpenAI', Provider.OPENAI),
		('ChatAnthropic', Provider.ANTHROPIC),
		('ChatGoogle', Provider.OPENROUTER),
		('ChatGemini', Provider.OPENROUTER),
		('ChatDeepSeek', Provider.DEEPSEEK),
		('ChatGroq', Provider.OPENROUTER),
	],
)
def test_provider_inferred_from_llm_class(class_name, expected):
	llm = _llm_class(class_name)(model='m', api_key='k')
	assert Agent(task='x', llm=llm).provider is expected


def test_provider_defaults_to_openai_when_llm_unknown_or_missing():
	assert Agent(task='x').provider is Provider.OPENAI
	llm = _llm_class('ChatTotallyMadeUp')(model='m')
	assert Agent(task='x', llm=llm).provider is Provider.OPENAI


def test_model_read_from_llm():
	llm = _llm_class('ChatOpenAI')(model='gpt-5')
	assert Agent(task='x', llm=llm)._model == 'gpt-5'


def test_api_key_read_from_llm_and_routed_to_provider_env_var():
	llm = _llm_class('ChatAnthropic')(model='c', api_key='sk-ant-test')
	env = Agent(task='x', llm=llm)._env_overrides()
	assert env.get('ANTHROPIC_API_KEY') == 'sk-ant-test'


def test_api_key_routes_openrouter_for_google_class():
	llm = _llm_class('ChatGoogle')(model='g', api_key='sk-or-test')
	env = Agent(task='x', llm=llm)._env_overrides()
	assert env.get('OPENROUTER_API_KEY') == 'sk-or-test'


def test_default_browser_mode_is_managed_headless_to_skip_chrome_dialog():
	"""Eval-critical: without this, the agent calls `browser connect local`
	on macOS, which waits for an "Allow remote debugging" click — infinite
	hang in CI / headless runs."""
	env = Agent(task='x')._env_overrides()
	assert env.get('LLM_BROWSER_BROWSER_MODE') == 'managed-headless'


def test_browser_headless_false_picks_managed_headed():
	class _Profile:
		headless = False

	class _Browser:
		browser_profile = _Profile()

	env = Agent(task='x', browser=_Browser())._env_overrides()
	assert env.get('LLM_BROWSER_BROWSER_MODE') == 'managed-headed'


def test_browser_name_passes_through_to_cli_flag():
	class _Browser:
		name = 'Local Chrome'

	flags = Agent(task='x', browser=_Browser())._cli_flags_excluding_task()
	assert '--browser' in flags
	assert 'Local Chrome' in flags


def test_rust_wrapper_disables_shell_tool_by_default(monkeypatch):
	monkeypatch.delenv('BU_RUST_ENABLE_SHELL_TOOL', raising=False)

	flags = Agent(task='x')._global_cli_flags()

	assert '-c' in flags
	assert 'features.shell_tool=false' in flags


def test_rust_wrapper_shell_tool_can_be_explicitly_enabled(monkeypatch):
	monkeypatch.setenv('BU_RUST_ENABLE_SHELL_TOOL', '1')

	flags = Agent(task='x')._global_cli_flags()

	assert 'features.shell_tool=false' not in flags


def test_rust_wrapper_respects_explicit_shell_tool_extra_arg(monkeypatch):
	monkeypatch.delenv('BU_RUST_ENABLE_SHELL_TOOL', raising=False)

	flags = Agent(task='x', extra_args=['-c', 'features.shell_tool=true'])._global_cli_flags()

	assert flags.count('features.shell_tool=false') == 0
	assert 'features.shell_tool=true' not in flags


def test_rust_wrapper_disables_non_browser_tools_by_default(monkeypatch):
	monkeypatch.delenv('BU_RUST_ENABLE_SHELL_TOOL', raising=False)

	flags = Agent(task='x')._global_cli_flags()

	for feature in [
		'features.shell_tool=false',
		'features.workspace_tools=false',
		'features.plugins=false',
		'features.image_generation=false',
	]:
		assert feature in flags


def test_rust_wrapper_respects_explicit_non_browser_tool_extra_args(monkeypatch):
	monkeypatch.delenv('BU_RUST_ENABLE_SHELL_TOOL', raising=False)

	flags = Agent(
		task='x',
		extra_args=[
			'-c',
			'features.workspace_tools=true',
			'-c',
			'features.plugins=true',
			'-c',
			'features.image_generation=true',
		],
	)._global_cli_flags()

	assert 'features.workspace_tools=false' not in flags
	assert 'features.plugins=false' not in flags
	assert 'features.image_generation=false' not in flags
	assert 'features.shell_tool=false' in flags


def test_rust_wrapper_enables_multi_agent_v2_in_eval_mode(monkeypatch):
	monkeypatch.setenv('BU_RUST_FORCE_SCREENSHOTS', '1')

	flags = Agent(task='x')._global_cli_flags()

	assert 'features.multi_agent_v2.enabled=true' in flags


def test_rust_wrapper_respects_explicit_multi_agent_v2_eval_override(monkeypatch):
	monkeypatch.setenv('BU_RUST_FORCE_SCREENSHOTS', '1')

	flags = Agent(task='x', extra_args=['-c', 'features.multi_agent_v2.enabled=false'])._global_cli_flags()

	assert 'features.multi_agent_v2.enabled=true' not in flags


def test_rust_wrapper_moves_config_extra_args_before_headless_subcommand(monkeypatch):
	from pathlib import Path

	from browser_use.rust import service
	from browser_use.rust.views import AgentRunResult

	seen_argv: list[str] = []

	async def fake_subprocess_exec(*argv, **kwargs):
		seen_argv.extend(str(arg) for arg in argv)

		class _Stream:
			async def read(self, _n=-1):
				return b''

		class _Proc:
			stdout = _Stream()
			stderr = _Stream()
			returncode = 0

			async def wait(self):
				return 0

		return _Proc()

	monkeypatch.setattr(service, 'find_browser_use_terminal_binary', lambda: Path('/tmp/browser-use-terminal'))
	monkeypatch.setattr(service, '_binary_supports_max_turns', lambda cli, subcommand: False)
	monkeypatch.setattr(service.asyncio, 'create_subprocess_exec', fake_subprocess_exec)

	agent = Agent(task='x', extra_args=['-c', 'features.shell_tool=true', '--some-subcmd-flag'])
	result = asyncio.run(agent._run_headless('do work', attach_to_session=None))

	assert isinstance(result, AgentRunResult)
	subcommand_index = seen_argv.index('run-openai')
	assert seen_argv[0] == '/tmp/browser-use-terminal'
	assert seen_argv[subcommand_index - 2 : subcommand_index] == ['-c', 'features.shell_tool=true']
	assert seen_argv[-1] == '--some-subcmd-flag'


def test_rust_wrapper_runs_headless_from_clean_runtime_cwd(monkeypatch, tmp_path):
	from pathlib import Path

	from browser_use.rust import service

	seen_kwargs: dict[str, object] = {}

	async def fake_subprocess_exec(*_argv, **kwargs):
		seen_kwargs.update(kwargs)

		class _Stream:
			async def read(self, _n=-1):
				return b''

		class _Proc:
			stdout = _Stream()
			stderr = _Stream()
			returncode = 0

			async def wait(self):
				return 0

		return _Proc()

	monkeypatch.delenv('BU_RUST_RUNTIME_CWD', raising=False)
	monkeypatch.setattr(service, 'find_browser_use_terminal_binary', lambda: Path('/tmp/browser-use-terminal'))
	monkeypatch.setattr(service, '_binary_supports_max_turns', lambda cli, subcommand: False)
	monkeypatch.setattr(service.asyncio, 'create_subprocess_exec', fake_subprocess_exec)

	state_dir = tmp_path / 'state'
	asyncio.run(Agent(task='x', state_dir=state_dir)._run_headless('do work', attach_to_session=None))

	assert seen_kwargs['cwd'] == state_dir / 'browser-agent-cwd'
	assert (state_dir / 'browser-agent-cwd').is_dir()


def test_rust_wrapper_runtime_cwd_env_override(monkeypatch, tmp_path):
	from browser_use.rust.service import _runtime_cwd

	override = tmp_path / 'browser-cwd'
	monkeypatch.setenv('BU_RUST_RUNTIME_CWD', str(override))

	assert _runtime_cwd(tmp_path / 'state') == override


def test_browser_cdp_url_passes_through_to_env_for_rust_side():
	class _Browser:
		cdp_url = 'ws://127.0.0.1:9222/devtools/browser/abc'

	env = Agent(task='x', browser=_Browser())._env_overrides()
	assert env.get('BUT_BROWSER_CDP_URL') == 'ws://127.0.0.1:9222/devtools/browser/abc'
	assert env.get('LLM_BROWSER_REMOTE_CDP_URL') == 'ws://127.0.0.1:9222/devtools/browser/abc'


def test_browser_session_alias_drives_remote_cdp_attach_env():
	"""Eval passes browser_session=BrowserSession(..., cdp_url=...). The Rust
	wrapper must treat that as browser= so it attaches to the pre-provisioned
	Unikraft/cloud browser instead of launching a fresh local Chromium."""

	class _BrowserSession:
		cdp_url = 'wss://unikraft.example/devtools/browser/eval'

	agent = Agent(task='x', browser_session=_BrowserSession())
	assert agent.browser is not None
	env = agent._env_overrides()
	assert env['LLM_BROWSER_BROWSER_MODE'] == 'managed-headless'
	assert env['LLM_BROWSER_REMOTE_CDP_URL'] == 'wss://unikraft.example/devtools/browser/eval'
	assert env['BUT_BROWSER_CDP_URL'] == 'wss://unikraft.example/devtools/browser/eval'


def test_browser_proxy_and_headless_and_channel_forwarded_via_env():
	class _Profile:
		proxy = type('P', (), {'server': 'http://proxy.example.com:8080'})()
		headless = True
		user_data_dir = '/tmp/profile'
		channel = 'chromium'

	class _Browser:
		browser_profile = _Profile()

	env = Agent(task='x', browser=_Browser())._env_overrides()
	assert env['BUT_BROWSER_PROXY'] == 'http://proxy.example.com:8080'
	assert env['BUT_BROWSER_HEADLESS'] == '1'
	assert env['BUT_BROWSER_USER_DATA_DIR'] == '/tmp/profile'
	assert env['BUT_BROWSER_CHANNEL'] == 'chromium'


def test_state_dir_appears_in_cli_flags():
	flags = Agent(task='x', state_dir='/tmp/foo')._cli_flags_excluding_task()
	assert '--state-dir' in flags and '/tmp/foo' in flags


def test_known_legacy_kwargs_are_silently_accepted():
	"""Common browser-use Agent kwargs that eval harnesses pass must NOT warn."""
	with warnings.catch_warnings(record=True) as caught:
		warnings.simplefilter('always')
		Agent(
			task='x',
			use_vision=True,
			save_conversation_path='/tmp/x.json',
			controller=object(),
			source='eval_platform',
			calculate_cost=True,
			use_judge=False,
			ground_truth='answer',
		)
	assert not caught, f'expected no warnings; got {[str(w.message) for w in caught]}'


def test_truly_unknown_kwargs_still_emit_warning():
	with warnings.catch_warnings(record=True) as caught:
		warnings.simplefilter('always')
		Agent(task='x', completely_made_up_kwarg=True)
	assert caught
	assert 'completely_made_up_kwarg' in str(caught[-1].message)


# ---------------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------------


def test_event_parse_known_type():
	payload = {
		'seq': 100,
		'id': 'abc',
		'session_id': 'sess',
		'ts_ms': 1700000000,
		'type': 'session.result',
		'payload': {'result': 'hello'},
	}
	event = parse_event(payload)
	assert isinstance(event, SessionResult)
	assert event.text == 'hello'


def test_event_parse_unknown_falls_back_to_raw():
	payload = {
		'seq': 1,
		'id': 'abc',
		'session_id': 'sess',
		'ts_ms': 1700000000,
		'type': 'brand.new.future.event',
		'payload': {'foo': 'bar'},
	}
	event = parse_event(payload)
	assert isinstance(event, RawEvent)
	assert event.type == 'brand.new.future.event'


def test_event_parse_blank_or_garbage_yields_none():
	assert parse_event('') is None
	assert parse_event('   ') is None
	assert parse_event('not json') is None
	assert parse_event(b'{"missing":"fields"}') is None


def test_event_parse_accepts_bytes_and_str_and_dict():
	payload = '{"seq":1,"id":"a","session_id":"s","ts_ms":1,"type":"session.input","payload":{"text":"hi"}}'
	assert isinstance(parse_event(payload), SessionInput)
	assert isinstance(parse_event(payload.encode()), SessionInput)
	assert isinstance(parse_event(json.loads(payload)), SessionInput)


# ---------------------------------------------------------------------------
# Session state machine
# ---------------------------------------------------------------------------


def _event(type_, payload, seq=1, session_id='s', ts_ms=None):
	return {
		'seq': seq,
		'id': f'id-{seq}',
		'session_id': session_id,
		'ts_ms': ts_ms if ts_ms is not None else seq * 1000,
		'type': type_,
		'payload': payload,
	}


def test_session_state_pairs_tool_call_with_result():
	state = _AgentSessionState()
	# Real Rust emits model.tool_call → tool.started → tool.finished.
	state.absorb(parse_event(_event('model.tool_call', {'name': 'browser.navigate', 'call_id': 'c1'}, seq=10)))
	state.absorb(parse_event(_event('tool.started', {'call_id': 'c1'}, seq=11)))
	state.absorb(parse_event(_event('tool.finished', {'call_id': 'c1', 'ok': True}, seq=12)))
	assert len(state.steps) == 1
	assert state.steps[0].tool == 'browser.navigate'
	assert state.steps[0].tool_output == {'call_id': 'c1', 'ok': True}


def test_session_state_accumulates_token_usage_from_model_usage():
	state = _AgentSessionState()
	state.absorb(
		parse_event(
			_event(
				'model.usage',
				{'input_tokens': 100, 'output_tokens': 50, 'cost': 0.002},
				seq=1,
			)
		)
	)
	state.absorb(
		parse_event(
			_event(
				'model.usage',
				{'input_tokens': 200, 'output_tokens': 30, 'cost': 0.003},
				seq=2,
			)
		)
	)
	assert state.token_input_total == 300
	assert state.token_output_total == 80
	assert abs(state.cost_total_usd - 0.005) < 1e-9


def test_session_state_collects_input_messages_for_last_input_messages():
	state = _AgentSessionState()
	state.absorb(parse_event(_event('model.response.input_item', {'role': 'user', 'content': 'hi'}, seq=1)))
	state.absorb(parse_event(_event('model.response.input_item', {'role': 'system', 'content': 'be nice'}, seq=2)))
	assert state.input_messages == [{'role': 'user', 'content': 'hi'}, {'role': 'system', 'content': 'be nice'}]


def test_session_state_handles_out_of_order_seq_idempotently():
	state = _AgentSessionState()
	ev = parse_event(_event('session.result', {'result': 'done'}, seq=42))
	state.absorb(ev)
	state.absorb(ev)
	state.absorb(parse_event(_event('session.result', {'result': 'older'}, seq=10)))
	assert state.final_summary == 'done'
	assert [e.seq for e in state.events] == [42]


def test_session_state_captures_failure():
	state = _AgentSessionState()
	state.absorb(parse_event(_event('session.failure', {'error': 'oops'}, seq=5)))
	assert state.failure == 'oops'


def test_session_state_attaches_tool_image_path_to_matching_step(tmp_path):
	"""tool.image events emitted between model.tool_call and tool.finished should
	attach the on-disk PNG path to the corresponding step so the eval judge can
	render screenshots."""
	state = _AgentSessionState()
	state.absorb(
		parse_event(
			_event('model.tool_call', {'name': 'browser_script', 'call_id': 'c1'}, seq=1)
		)
	)
	state.absorb(parse_event(_event('tool.started', {'call_id': 'c1'}, seq=2)))
	state.absorb(
		parse_event(
			_event(
				'tool.image',
				{
					'name': 'browser_script',
					'tool_call_id': 'c1',
					'image': {'path': '/tmp/before.png', 'label': 'before'},
				},
				seq=3,
			)
		)
	)
	state.absorb(
		parse_event(
			_event(
				'tool.image',
				{
					'name': 'browser_script',
					'tool_call_id': 'c1',
					'image': {'path': '/tmp/after.png', 'label': 'after'},
				},
				seq=4,
			)
		)
	)
	state.absorb(parse_event(_event('tool.finished', {'call_id': 'c1', 'ok': True}, seq=5)))
	assert len(state.steps) == 1
	assert state.steps[0].screenshot_paths == ['/tmp/before.png', '/tmp/after.png']


def test_session_state_tool_output_images_array_attached_to_step():
	"""tool.output for browser_script carries an `images` array — those paths
	should also land on the step (alongside tool.image events)."""
	state = _AgentSessionState()
	state.absorb(
		parse_event(_event('model.tool_call', {'name': 'browser_script', 'call_id': 'c2'}, seq=1))
	)
	state.absorb(
		parse_event(
			_event(
				'tool.output',
				{
					'name': 'browser_script',
					'tool_call_id': 'c2',
					'images': [{'path': '/tmp/x.png'}, {'path': '/tmp/y.png'}],
				},
				seq=2,
			)
		)
	)
	state.absorb(parse_event(_event('tool.finished', {'call_id': 'c2', 'ok': True}, seq=3)))
	assert state.steps[0].screenshot_paths == ['/tmp/x.png', '/tmp/y.png']


def test_history_view_reads_screenshot_b64_from_disk(tmp_path):
	"""AgentRunResult.history[i].state.get_screenshot() returns base64 PNG bytes
	read from the path the Rust core emitted. This is what the eval judge consumes."""
	import base64

	from browser_use.rust.views import AgentRunResult, StepRecord

	# Write a tiny PNG-ish blob to disk; the wrapper just base64-encodes
	# whatever the path points at — it doesn't validate the magic bytes.
	png_path = tmp_path / 'shot.png'
	png_path.write_bytes(b'\x89PNG\r\n\x1a\nfake')

	result = AgentRunResult(
		exit_code=0,
		final_summary='done',
		steps=[
			StepRecord(
				seq=1,
				tool='browser_script',
				tool_input=None,
				tool_output={'ok': True},
				model_text='',
				screenshot_paths=[str(png_path)],
			)
		],
	)
	hist = result.history
	assert len(hist) == 1
	b64 = hist[0].state.get_screenshot()
	assert b64 is not None
	assert base64.b64decode(b64) == b'\x89PNG\r\n\x1a\nfake'


def test_eval_screenshot_directive_appends_only_when_env_set(monkeypatch):
	"""BU_RUST_FORCE_SCREENSHOTS=1 appends the directive; unset/anything else is a no-op."""
	from browser_use.rust.service import _maybe_inject_eval_directive

	monkeypatch.delenv('BU_RUST_FORCE_SCREENSHOTS', raising=False)
	assert _maybe_inject_eval_directive('go to example.com') == 'go to example.com'

	monkeypatch.setenv('BU_RUST_FORCE_SCREENSHOTS', '1')
	out = _maybe_inject_eval_directive('go to example.com', max_turns=150)
	assert out is not None
	assert '[EVAL MODE' in out
	assert 'Max turns: 150' in out
	assert 'spawn one focused sub-agent per item/document/site' in out
	assert 'short snake_case `task_name`' in out
	assert 'collect with `wait_agent` without targets' in out
	assert '`agent_status.completed` values' in out
	# Idempotent — re-injecting must not duplicate.
	assert _maybe_inject_eval_directive(out, max_turns=200) == out

	default_budget = _maybe_inject_eval_directive('go to example.org')
	assert default_budget is not None
	assert 'Max turns: 80' in default_budget

	# None passes through unchanged.
	assert _maybe_inject_eval_directive(None) is None


def test_skipped_browsing_retry_keeps_remote_cdp_attach_first(monkeypatch):
	from browser_use.rust import AgentRunResult
	from browser_use.rust.views import StepRecord

	class _Browser:
		cdp_url = 'wss://unikraft.example/devtools/browser/eval'

	calls: list[str] = []

	async def fake_run_headless(self, text, *, attach_to_session, subcommand=None, max_turns=None):
		calls.append(text)
		if len(calls) == 1:
			return AgentRunResult(
				exit_code=0,
				steps=[
					StepRecord(
						seq=1,
						tool='browser',
						tool_input={'arguments': {'command': 'status'}},
						tool_output={'ok': True},
					)
				],
			)
		return AgentRunResult(
			exit_code=0,
			steps=[
				StepRecord(
					seq=2,
					tool='browser_script',
					tool_input={'arguments': {'code': 'await page.goto("https://example.com")'}},
					tool_output={'ok': True},
				)
			],
		)

	monkeypatch.setenv('BU_RUST_FORCE_SCREENSHOTS', '1')
	monkeypatch.setattr(Agent, '_run_headless', fake_run_headless)

	agent = Agent(task='go to example.com and report the title', browser_session=_Browser())
	asyncio.run(agent.run(max_steps=150))

	assert len(calls) == 2
	assert calls[0].startswith('[BROWSER ATTACH')
	assert calls[1].startswith('[BROWSER ATTACH')
	assert calls[1].index('[CRITICAL RETRY]') > calls[1].index('Skip the connect step')
	assert 'After any required browser attach action' in calls[1]


def test_max_turns_extra_arg_detection_handles_equals_form():
	from browser_use.rust.service import _has_max_turns_arg

	assert _has_max_turns_arg(['--max-turns', '150']) is True
	assert _has_max_turns_arg(['--max-turns=150']) is True
	assert _has_max_turns_arg(['--model', 'claude-sonnet-4-6']) is False


def test_laminar_trace_url_formats_hex_as_uuid():
	"""Laminar requires UUID format (8-4-4-4-12); Rust emits raw 32-hex.
	URL builder must convert so the dashboard link actually opens the trace."""
	from browser_use.rust.views import AgentRunResult, _format_trace_id_as_uuid

	# 32-hex pass-through case
	assert _format_trace_id_as_uuid('97db9503a669d1d1507e6459b46660f7') == '97db9503-a669-d1d1-507e-6459b46660f7'
	# Already UUID-formatted: passthrough
	assert _format_trace_id_as_uuid('97db9503-a669-d1d1-507e-6459b46660f7') == '97db9503-a669-d1d1-507e-6459b46660f7'
	# Garbage: passthrough (caller deals with it)
	assert _format_trace_id_as_uuid('not-a-trace-id') == 'not-a-trace-id'
	assert _format_trace_id_as_uuid('') == ''

	# End-to-end URL
	state = _AgentSessionState()
	state.absorb(parse_event(_event('telemetry.trace', {'backend': 'laminar', 'trace_id': '97db9503a669d1d1507e6459b46660f7'}, seq=1)))
	r = AgentRunResult(exit_code=0, events=state.events, steps=state.steps)
	url = r.laminar_trace_url(project_id='proj-123')
	assert url == 'https://laminar.sh/project/proj-123/traces?traceId=97db9503-a669-d1d1-507e-6459b46660f7'


def test_step_timing_populated_from_tool_started_and_finished():
	"""Per-step duration must come from tool.started→tool.finished ts_ms so
	the eval dashboard doesn't show 30s/step nonsense averages."""
	state = _AgentSessionState()
	state.absorb(parse_event(_event('model.tool_call', {'name': 'browser_script', 'id': 'tc1'}, seq=1, ts_ms=1_700_000_000_000)))
	state.absorb(parse_event(_event('tool.started', {'tool_call_id': 'tc1'}, seq=2, ts_ms=1_700_000_000_100)))
	state.absorb(parse_event(_event('tool.finished', {'name': 'browser_script', 'tool_call_id': 'tc1'}, seq=3, ts_ms=1_700_000_003_500)))
	step = state.steps[0]
	assert step.started_ts_ms == 1_700_000_000_100
	assert step.finished_ts_ms == 1_700_000_003_500

	from browser_use.rust.views import _HistoryItemView
	hv = _HistoryItemView(step, is_last=True, final_summary=None)
	assert abs(hv.metadata.duration_seconds - 3.4) < 0.01
	assert hv.metadata.step_start_time > 1_000_000_000  # sane unix timestamp


def test_tool_output_text_promoted_to_extracted_content():
	"""tool.output events carry the actual script output in `text`/`data`/etc.
	The wrapper must merge that into step.tool_output (alongside tool.finished's
	{name, tool_call_id}) and synthesise extracted_content for the judge."""
	state = _AgentSessionState()
	state.absorb(parse_event(_event('model.tool_call', {'name': 'browser_script', 'id': 'tc1', 'arguments': {'code': 'print(page_info())'}}, seq=1)))
	state.absorb(parse_event(_event('tool.started', {'tool_call_id': 'tc1'}, seq=2)))
	state.absorb(parse_event(_event('tool.finished', {'name': 'browser_script', 'tool_call_id': 'tc1'}, seq=3)))
	state.absorb(parse_event(_event('tool.output', {'name': 'browser_script', 'tool_call_id': 'tc1', 'text': 'Example Domain\n', 'status': 'finished', 'ok': True}, seq=4)))
	step = state.steps[0]
	assert step.tool_output is not None
	assert step.tool_output.get('text') == 'Example Domain\n'
	assert step.tool_output.get('status') == 'finished'
	assert step.tool_output.get('extracted_content') == 'Example Domain\n'


def test_tool_output_structured_ready_signals_promoted_to_extracted_content():
	"""Structured browser_script results can carry the ready answer/artifact
	without a text transcript. Keep those visible to the judge/history view."""
	state = _AgentSessionState()
	state.absorb(parse_event(_event('model.tool_call', {'name': 'browser_script', 'id': 'tc1'}, seq=1)))
	state.absorb(parse_event(_event('tool.output', {
		'name': 'browser_script',
		'tool_call_id': 'tc1',
		'final_candidate': {'ready_for_done': True, 'answer': '42'},
		'result_file_candidates': [{'path': '/tmp/result.json', 'bytes': 18}],
		'status': 'finished',
		'ok': True,
	}, seq=2)))
	step = state.steps[0]
	assert step.tool_output is not None
	assert step.tool_output.get('final_candidate') == {'ready_for_done': True, 'answer': '42'}
	assert step.tool_output.get('result_file_candidates') == [{'path': '/tmp/result.json', 'bytes': 18}]
	extracted = json.loads(step.tool_output['extracted_content'])
	assert extracted['final_candidate']['ready_for_done'] is True
	assert extracted['result_file_candidates'][0]['path'] == '/tmp/result.json'


def test_response_input_tool_output_attaches_wait_agent_results_to_step():
	"""Generic JSON tool outputs are persisted as model.response.input_item events.
	Attach them to the step so V2 wait_agent child results reach AgentHistory views."""
	state = _AgentSessionState()
	state.absorb(parse_event(_event('model.tool_call', {'name': 'wait_agent', 'id': 'tc1'}, seq=1)))
	state.absorb(parse_event(_event('tool.finished', {'name': 'wait_agent', 'tool_call_id': 'tc1'}, seq=2)))
	state.absorb(parse_event(_event('model.response.input_item', {
		'source': 'tool_output',
		'name': 'wait_agent',
		'call_id': 'tc1',
		'item': {
			'type': 'function_call_output',
			'call_id': 'tc1',
			'output': json.dumps({
				'message': 'Wait completed.',
				'timed_out': False,
				'agents': [
					{
						'agent_name': '/root/item_1',
						'agent_status': {'completed': 'child answer'},
						'last_task_message': 'inspect item 1',
					}
				],
			}),
		},
	}, seq=3)))
	step = state.steps[0]
	assert step.tool_output is not None
	assert step.tool_output['message'] == 'Wait completed.'
	assert step.tool_output['agents'][0]['agent_status'] == {'completed': 'child answer'}
	extracted = json.loads(step.tool_output['extracted_content'])
	assert extracted['agents'][0]['agent_status']['completed'] == 'child answer'
	assert extracted['timed_out'] is False


def test_response_output_item_message_text_attached_to_step():
	"""LLM messages between tool calls (the agent's reasoning prose) should
	land on the most recent step's model_text so the judge sees the chain
	of thought / commentary."""
	state = _AgentSessionState()
	state.absorb(parse_event(_event('model.tool_call', {'name': 'browser', 'id': 'tc1'}, seq=1)))
	# OpenAI/Codex output_item with content list
	state.absorb(parse_event(_event('model.response.output_item', {'type': 'message', 'content': [{'type': 'output_text', 'text': 'I went to example.com and read the title.'}]}, seq=2)))
	assert state.steps[0].model_text == 'I went to example.com and read the title.'

	# Reasoning items must NOT leak into model_text
	state.absorb(parse_event(_event('model.response.output_item', {'type': 'reasoning', 'content': []}, seq=3)))
	assert state.steps[0].model_text == 'I went to example.com and read the title.'


def test_looks_like_skip_classification():
	"""Match the agent's training-data-shortcut pattern: 0-2 steps, all of which
	are browser admin calls or observe polls. Any real browser_script code call
	or extra tool means the agent actually browsed."""
	from browser_use.rust.service import _looks_like_skip
	from browser_use.rust.views import AgentRunResult, StepRecord

	# 0 steps → no work happened at all (counts as skip)
	r = AgentRunResult(exit_code=0, steps=[])
	assert _looks_like_skip(r) is True

	# Only browser admin
	r = AgentRunResult(exit_code=0, steps=[
		StepRecord(seq=1, tool='browser', tool_input={'arguments': {'cmd': 'status --json'}}, model_text=''),
	])
	assert _looks_like_skip(r) is True

	# observe-mode browser_script is still a skip (no real page interaction)
	r = AgentRunResult(exit_code=0, steps=[
		StepRecord(seq=1, tool='browser', tool_input={'arguments': {'cmd': 'status --json'}}, model_text=''),
		StepRecord(seq=2, tool='browser_script', tool_input={'arguments': {'action': 'observe', 'observe_timeout_ms': 2000}}, model_text=''),
	])
	assert _looks_like_skip(r) is True

	# code-mode browser_script = real browsing
	r = AgentRunResult(exit_code=0, steps=[
		StepRecord(seq=1, tool='browser', tool_input={'arguments': {'cmd': 'status --json'}}, model_text=''),
		StepRecord(seq=2, tool='browser_script', tool_input={'arguments': {'code': 'new_tab("https://example.com")'}}, model_text=''),
	])
	assert _looks_like_skip(r) is False

	# 3+ steps → automatically not a skip
	r = AgentRunResult(exit_code=0, steps=[
		StepRecord(seq=1, tool='browser', tool_input={'arguments': {'cmd': 'status --json'}}, model_text=''),
		StepRecord(seq=2, tool='browser', tool_input={'arguments': {'cmd': 'connect managed --headless'}}, model_text=''),
		StepRecord(seq=3, tool='browser', tool_input={'arguments': {'cmd': 'status --json'}}, model_text=''),
	])
	assert _looks_like_skip(r) is False


def test_compact_tool_input_strips_observe_noise():
	"""browser_script(action=observe, observe_timeout_ms, run_id) is internal
	browser-state polling. Judge doesn't need 300 chars of poll metadata per step."""
	from browser_use.rust.views import _compact_tool_input

	noisy = {
		'arguments': {'action': 'observe', 'observe_timeout_ms': 2000, 'run_id': 'bs-1780125407172-1'},
		'id': 'call_xyz',
		'name': 'browser_script',
	}
	out = _compact_tool_input('browser_script', noisy)
	assert out['arguments'] == {'action': 'observe', 'note': 'internal browser-state poll'}
	assert out['id'] == 'call_xyz'  # passthrough

	# A real `code` browser_script must pass through untouched
	code_call = {
		'arguments': {'code': 'screenshot("x")\nresult = "ok"'},
		'id': 'call_abc',
		'name': 'browser_script',
	}
	out2 = _compact_tool_input('browser_script', code_call)
	assert out2['arguments']['code'].startswith('screenshot')

	# Non-browser_script tools pass through unchanged
	other = {'arguments': {'cmd': 'status --json'}, 'id': 'c1', 'name': 'browser'}
	assert _compact_tool_input('browser', other) is other


def test_history_view_returns_none_when_screenshot_path_missing():
	"""Missing or unreadable screenshot files must not crash the history view."""
	from browser_use.rust.views import AgentRunResult, StepRecord

	result = AgentRunResult(
		exit_code=0,
		final_summary='done',
		steps=[
			StepRecord(
				seq=1,
				tool='browser_script',
				tool_input=None,
				tool_output={'ok': True},
				model_text='',
				screenshot_paths=['/nonexistent/path/that/should/not/exist.png'],
			)
		],
	)
	assert result.history[0].state.get_screenshot() is None


def test_compute_cost_usd_for_known_model(tmp_path):
	"""TokenCost lookup should yield a non-zero $ cost for a priced model."""
	import asyncio

	from browser_use.rust.service import _compute_cost_usd

	cost = asyncio.run(_compute_cost_usd('gpt-4o-mini', 100_000, 5_000))
	# gpt-4o-mini is $0.15/1M input, $0.60/1M output → ~$0.018 for this load.
	assert 0.001 < cost < 0.10, f'unexpected cost: {cost}'


def test_compute_cost_usd_returns_zero_for_unknown_or_empty():
	"""Unknown model name or zero tokens must return 0.0, not raise."""
	import asyncio

	from browser_use.rust.service import _compute_cost_usd

	assert asyncio.run(_compute_cost_usd(None, 1000, 100)) == 0.0
	assert asyncio.run(_compute_cost_usd('gpt-5', 0, 0)) == 0.0


def test_laminar_trace_id_extracted_from_telemetry_trace_event():
	"""AgentRunResult.laminar_trace_id reads the first telemetry.trace event's
	trace_id. URL builder returns None without a project id."""
	state = _AgentSessionState()
	state.absorb(
		parse_event(
			_event(
				'telemetry.trace',
				{'backend': 'laminar', 'transport': 'otlp_http_proto', 'trace_id': '0123456789abcdef', 'endpoint': 'https://api.lmnr.ai'},
				seq=1,
			)
		)
	)
	from browser_use.rust.views import AgentRunResult

	result = AgentRunResult(exit_code=0, events=state.events, steps=state.steps)
	assert result.laminar_trace_id == '0123456789abcdef'
	# No project id available → None
	url_none = result.laminar_trace_url(project_id=None)
	assert url_none is None or 'laminar.sh' in url_none
	url = result.laminar_trace_url(project_id='proj123')
	# 16-hex trace_id (not 32) passes through un-formatted (the UUID formatter
	# only converts 32-hex strings); URL still works for diagnostic purposes.
	assert url == 'https://laminar.sh/project/proj123/traces?traceId=0123456789abcdef'


def test_agent_laminar_trace_id_property_delegates_to_result():
	"""Agent.laminar_trace_id returns None before run, the result's trace id after."""
	from browser_use.rust.views import AgentRunResult

	agent = Agent(task='x')
	assert agent.laminar_trace_id is None

	agent.result = AgentRunResult(exit_code=0, events=[])
	assert agent.result.laminar_trace_id is None


def test_resolve_judge_llm_prefers_gemini_when_key_set(monkeypatch):
	"""GEMINI_API_KEY → ChatGoogle judge; OPENAI_API_KEY-only → ChatOpenAI judge;
	neither → None (caller skips judging)."""
	from browser_use.rust.service import _resolve_judge_llm

	monkeypatch.delenv('GEMINI_API_KEY', raising=False)
	monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
	monkeypatch.delenv('OPENAI_API_KEY', raising=False)
	assert _resolve_judge_llm() is None

	monkeypatch.setenv('OPENAI_API_KEY', 'sk-test')
	llm = _resolve_judge_llm()
	assert llm is not None
	# ChatOpenAI fallback
	assert type(llm).__name__ == 'ChatOpenAI'

	monkeypatch.setenv('GEMINI_API_KEY', 'gm-test')
	llm = _resolve_judge_llm()
	assert llm is not None
	# Gemini preferred when key present
	assert type(llm).__name__ == 'ChatGoogle'


def test_judgement_round_trip_via_is_judged_and_judgement():
	"""eval harness reads agent.history.is_judged() / .judgement() — both must
	reflect what Agent._judge_and_log stashed."""
	from browser_use.rust.views import AgentRunResult

	r = AgentRunResult(exit_code=0, final_summary='done')
	assert r.is_judged() is False
	assert r.judgement() is None

	r.judgement_dict = {
		'verdict': True,
		'reasoning': 'looked plausible',
		'failure_reason': '',
		'impossible_task': False,
		'reached_captcha': False,
	}
	assert r.is_judged() is True
	out = r.judgement()
	assert out is not None
	assert out['verdict'] is True
	assert out['reasoning'] == 'looked plausible'


# ---------------------------------------------------------------------------
# Structured output
# ---------------------------------------------------------------------------


class _Receipt(BaseModel):
	store: str
	total: float


def test_output_model_parses_plain_json():
	agent = Agent(task='x', output_model=_Receipt)
	parsed = agent._parse_output_model('{"store": "BU", "total": 12.5}')
	assert isinstance(parsed, _Receipt)
	assert parsed.total == 12.5


def test_output_model_parses_fenced_json():
	agent = Agent(task='x', output_model=_Receipt)
	body = 'Sure! Here is the data:\n```json\n{"store": "BU", "total": 0.0}\n```\nLet me know.'
	parsed = agent._parse_output_model(body)
	assert isinstance(parsed, _Receipt)


def test_output_model_returns_none_when_no_json_anywhere():
	agent = Agent(task='x', output_model=_Receipt)
	assert agent._parse_output_model('no structured payload') is None


# ---------------------------------------------------------------------------
# AgentHistoryList-compatible eval surface
# ---------------------------------------------------------------------------


def test_result_quacks_like_agent_history_list():
	from browser_use.rust import AgentRunResult
	from browser_use.rust.views import StepRecord

	result = AgentRunResult(
		session_id='sess',
		exit_code=0,
		final_summary='the answer is 42',
		steps=[
			StepRecord(seq=1, tool='browser.navigate', tool_input={'url': 'https://x'}, tool_output={'ok': True}),
			StepRecord(seq=2, tool='done', tool_input=None, tool_output={'extracted_content': 'the answer is 42'}),
		],
	)
	# The five methods most eval harnesses call on AgentHistoryList:
	assert result.final_result() == 'the answer is 42'
	assert result.is_done() is True
	assert result.is_successful() is True
	assert result.errors() == [None, None]
	assert result.has_errors() is False
	assert result.action_names() == ['browser.navigate', 'done']
	assert len(result) == 2

	# .history is iterable like the legacy AgentHistoryList
	steps = result.history
	assert len(steps) == 2
	assert steps[0].state.url is None  # not propagated from Rust yet
	assert steps[0].result[0].extracted_content is None or steps[0].result[0].extracted_content == {'ok': True}
	# model_output is dict-shape: {'action': [{tool_name: input}], 'current_state': {...}}
	first_action = steps[0].model_output.action
	assert isinstance(first_action, list) and first_action and 'browser.navigate' in first_action[0]

	# .usage with .model_dump()
	dump = result.usage.model_dump()
	assert set(dump) >= {'input_tokens', 'output_tokens', 'cost', 'model'}


def test_final_summary_does_not_mark_non_done_step_successful():
	from browser_use.rust import AgentRunResult
	from browser_use.rust.views import StepRecord

	result = AgentRunResult(
		session_id='sess',
		exit_code=0,
		final_summary='the answer is 42',
		steps=[
			StepRecord(seq=1, tool='browser_script', tool_output={'text': 'looked at page'}),
		],
	)
	last = result.history[-1].result[0]
	assert last.extracted_content == 'looked at page'
	assert last.is_done is True
	assert last.success is None


def test_clean_exit_without_final_result_is_not_successful_or_done():
	from browser_use.rust import AgentRunResult
	from browser_use.rust.views import StepRecord

	result = AgentRunResult(
		session_id='sess',
		exit_code=0,
		final_summary=None,
		steps=[
			StepRecord(seq=1, tool='browser_script', tool_output={'text': 'looked at page'}),
		],
	)

	assert result.final_result() is None
	assert result.is_done() is False
	assert result.is_successful() is None
	last = result.history[-1].result[0]
	assert last.extracted_content == 'looked at page'
	assert last.is_done is False
	assert last.success is None


def test_message_manager_stub_is_present_for_eval_harness_read():
	from browser_use.rust import Agent

	agent = Agent(task='x')
	assert hasattr(agent, 'message_manager')
	assert agent.message_manager.last_input_messages == []


# ---------------------------------------------------------------------------
# Integration: requires the real `browser-use-terminal` binary
# ---------------------------------------------------------------------------


def _have_binary() -> bool:
	try:
		find_browser_use_terminal_binary()
		return True
	except ButNotInstalledError:
		return False


@pytest.mark.skipif(not _have_binary(), reason='browser-use-terminal not installed')
async def test_run_fake_end_to_end_via_explicit_provider_call():
	cli = find_browser_use_terminal_binary()
	proc = await asyncio.create_subprocess_exec(
		str(cli),
		'run-fake',
		'say hello and exit',
		stdout=asyncio.subprocess.PIPE,
		stderr=asyncio.subprocess.PIPE,
	)
	stdout_bytes, _ = await proc.communicate()
	assert proc.returncode == 0
	session_id = stdout_bytes.decode().strip().splitlines()[0]
	assert len(session_id) >= 8

	show_proc = await asyncio.create_subprocess_exec(
		str(cli),
		'show',
		session_id,
		stdout=asyncio.subprocess.PIPE,
		stderr=asyncio.subprocess.PIPE,
	)
	show_out, _ = await show_proc.communicate()
	text = show_out.decode()
	assert 'Result' in text
	assert 'Fake result for: say hello and exit' in text
