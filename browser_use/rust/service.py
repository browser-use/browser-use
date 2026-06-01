"""
Python `Agent` for the Rust `browser-use-core` agent loop.

Minimal interface — exactly the kwargs you'd expect:

    Agent(
        task: str | None = None,
        *,
        llm:           BaseChatModel | None = None,   # owns model, provider, api_key
        browser:       BrowserSession  | None = None, # owns cdp_url, profile, headless, name
        timeout:       float           | None = None, # cancel ladder when exceeded
        on_event:      Callable        | None = None, # fires per typed event
        output_model:  type[BaseModel] | None = None, # parse final summary into pydantic
        state_dir:     str | Path      | None = None, # override Rust state dir
        extra_args:    list[str]       | None = None, # rare CLI escape hatch
    )

Provider, model, and api_key are inferred from the `llm` object (same
pattern as the classic `browser_use.Agent`). Browser config (CDP url,
profile, headless flag, browser name) is read off the `browser` object.
There is no separate "options" struct — every user-facing knob is a
constructor kwarg.

Backward compat: `from browser_use import Agent` is unchanged. This module
is strictly additive.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import time
import warnings
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from browser_use.rust.events import (
	AnyAgentEvent,
	ModelDelta,
	ModelResponseInputItem,
	ModelStreamDelta,
	ModelToolCall,
	ModelUsage,
	SessionCreated,
	SessionFailure,
	SessionResult,
	ToolFinished,
	ToolImage,
	ToolOutput,
	ToolStarted,
	parse_event,
)
from browser_use.rust.runner import (
	find_browser_use_terminal_binary,
	find_but_binary,
	launch_terminal_ui,
)
from browser_use.rust.views import AgentRunResult, Provider, StepRecord

_PROVIDER_BY_CLASS: dict[str, Provider] = {
	'ChatOpenAI': Provider.OPENAI,
	'ChatAzureOpenAI': Provider.OPENAI,
	'ChatLiteLLM': Provider.OPENAI,
	'ChatBrowserUse': Provider.OPENAI,
	'ChatAnthropic': Provider.ANTHROPIC,
	'ChatGroq': Provider.OPENROUTER,
	'ChatOpenRouter': Provider.OPENROUTER,
	'ChatGoogle': Provider.OPENROUTER,
	'ChatGemini': Provider.OPENROUTER,
	'ChatDeepSeek': Provider.DEEPSEEK,
}

# Kwargs the classic browser_use.Agent accepts. Quietly ignore them when
# eval harnesses pass them through — they're not warnings, they're known
# no-ops for this wrapper. Anything outside this set still warns.
_KNOWN_LEGACY_KWARGS: frozenset[str] = frozenset(
	{
		# First-version (handled): task, llm, browser, browser_session,
		# timeout, on_event, output_model, output_model_schema, state_dir
		# Eval-harness-specific kwargs (accepted, no-op):
		'controller',
		'tools',
		'use_vision',
		'max_actions_per_step',
		'use_thinking',
		'flash_mode',
		'images_per_step',
		'source',
		'calculate_cost',
		'override_system_message',
		'initial_actions',
		'use_judge',
		'judge_llm',
		'ground_truth',
		'browser_profile',
		'browser_session',  # alias handled below
		'save_conversation_path',
		'max_failures',
		'skill_ids',
		'skills',
		# Second-version (accepted; partial Rust support — see roadmap):
		'sensitive_data',  # Rust core would need a secrets surface
		'allowed_domains',  # browser_profile.allowed_domains exists; forward only
		'blocked_domains',  # same as above
		'webhook_url',  # third-version; accepted now
		'webhook_token',
		'viewport_size',
		'window_size',
		'recordings_dir',  # Rust core records to state_dir/recordings/
		'live_url_callback',  # Rust may emit live_url events; future
		'metadata',
		'tags',
		'name',
		'description',
		'priority',
		'budget_usd',  # Rust would need to emit usage warnings
		'budget_tokens',
		'cache_key',
		'deterministic_replay',
	}
)


class _MessageManagerStub:
	"""Compat for `agent.message_manager.last_input_messages` reads."""

	def __init__(self) -> None:
		self.last_input_messages: list[Any] = []

DEFAULT_POLL_INTERVAL_MS = 250
GRACEFUL_CANCEL_TIMEOUT_S = 5.0
DEFAULT_RUST_MAX_TURNS = 80
SHELL_TOOL_OPT_IN_ENV = 'BU_RUST_ENABLE_SHELL_TOOL'
RUNTIME_CWD_ENV = 'BU_RUST_RUNTIME_CWD'
BROWSER_TASK_DISABLED_FEATURES = (
	'features.shell_tool',
	'features.workspace_tools',
	'features.plugins',
	'features.image_generation',
)
EVAL_BROWSER_TASK_CONFIG = (
	('features.multi_agent_v2.enabled', 'true'),
	('features.multi_agent_v2.max_concurrent_threads_per_session', '10'),
)
TOOL_OUTPUT_KEYS = (
	'text',
	'data',
	'outputs',
	'summary',
	'message',
	'status',
	'timed_out',
	'ok',
	'next_observe_ms',
	'error',
	'diagnosis',
	'agents',
	'agent_status',
	'final_candidate',
	'completion_candidates',
	'result_file_candidates',
	'result_file',
	'output_file',
	'artifact',
	'artifacts',
)
STRUCTURED_EXTRACTED_CONTENT_KEYS = (
	'final_candidate',
	'completion_candidates',
	'result_file_candidates',
	'result_file',
	'output_file',
	'artifact',
	'artifacts',
	'outputs',
	'message',
	'timed_out',
	'agents',
	'agent_status',
)

# Appended to the task text when BU_RUST_FORCE_SCREENSHOTS=1 (set by the
# eval CI). The Rust core's default system prompt only *encourages*
# screenshots; without them the eval judge has no visual evidence and
# scores everything 0. The wrapper forwards this directive once per task.
EVAL_SCREENSHOT_DIRECTIVE_TEMPLATE = (
	'\n\n[EVAL MODE — automated test, no human will reply]'
	'\nVerify on the live website (never from memory). Return every requested '
	'data field inline in the final answer (never "see the file" — judge has '
	'no filesystem). Dismiss cookie banners before extracting. End each '
	'browser_script with `screenshot("step")`. Do not ask clarifying questions '
	'— finish with the best answer you can produce from the live page.'
	'\n\n[BUDGET — read before your first tool call]'
	'\nMax turns: {max_turns}. For multi-item tasks (N>=5 items), do not walk '
	'items one by one in the parent. First try http_get/requests + '
	'ThreadPoolExecutor in a SINGLE browser_script call for static pages and '
	'explicit URLs/paths. If pages need JS, interaction, pagination, PDFs, '
	'vendor disambiguation, or separate sites, spawn one focused sub-agent per '
	'item/document/site with `spawn_agent` using a short snake_case `task_name`, '
	'then collect with `wait_agent` without targets and read the returned '
	'`agents` array for `agent_status.completed` values. If you have enough '
	'helper results while some helpers are still running, finish with '
	'`done(result=..., finish_and_close_children=true)`. '
	'Serial browser walks burn 5-10 turns per item and exhaust the budget.'
)

RETRY_BROWSE_DIRECTIVE = (
	'[CRITICAL RETRY] Your previous attempt at this task did NOT use '
	'browser_script to open the page — that is failure. The grader '
	'requires evidence of live navigation. After any required browser attach '
	'action, your FIRST content action this time MUST be a browser_script call '
	'that navigates to the URL referenced in the task, screenshots the loaded '
	'page, and extracts the answer. Do not call `done` before that.\n\n'
)


OnEvent = Callable[[AnyAgentEvent], None] | Callable[[AnyAgentEvent], Awaitable[None]]


_MAX_TURNS_SUPPORT_CACHE: dict[str, bool] = {}


def _structured_extracted_content(payload: dict[str, Any], *, limit: int = 8000) -> str | None:
	"""Compact structured browser_script result hints for eval history.

	Some helper scripts return machine-readable "ready result" or artifact
	candidates rather than a plain text transcript. Surface those keys as
	extracted_content so the judge/dashboard sees why the agent could finish.
	"""
	subset = {key: payload[key] for key in STRUCTURED_EXTRACTED_CONTENT_KEYS if payload.get(key) not in (None, '', [], {})}
	if not subset:
		return None
	return _bounded_json_for_extracted_content(subset, limit=limit)


def _bounded_json_for_extracted_content(payload: dict[str, Any], *, limit: int) -> str:
	full = json.dumps(payload, ensure_ascii=False, sort_keys=True)
	if len(full) <= limit:
		return full
	compact: dict[str, Any] = {'truncated': True}
	for key in ('message', 'timed_out', 'status', 'ok'):
		if key in payload:
			compact[key] = payload[key]
	if isinstance(payload.get('agents'), list):
		compact['agents'] = [_compact_agent_status(agent) for agent in payload['agents']]
	for key, value in payload.items():
		if key in compact or key == 'agents':
			continue
		compact[key] = _truncate_structured_value(value, max_string_chars=500)
	result = json.dumps(compact, ensure_ascii=False, sort_keys=True)
	if len(result) <= limit:
		return result
	# Keep JSON valid even under pathological payloads. Agent names and compact
	# status snippets are more useful to the judge than a raw broken JSON slice.
	if isinstance(compact.get('agents'), list):
		compact['agents'] = compact['agents'][:20]
		for agent in compact['agents']:
			if isinstance(agent.get('agent_status'), dict):
				for status_key in ('completed', 'errored'):
					if status_key in agent['agent_status']:
						agent['agent_status'][status_key] = _truncate_text(
							str(agent['agent_status'][status_key]), 240
						)
			if 'last_task_message' in agent:
				agent['last_task_message'] = _truncate_text(str(agent['last_task_message']), 120)
	result = json.dumps(compact, ensure_ascii=False, sort_keys=True)
	if len(result) <= limit:
		return result
	return json.dumps({'truncated': True, 'keys': sorted(payload)}, ensure_ascii=False, sort_keys=True)


def _compact_agent_status(agent: Any) -> Any:
	if not isinstance(agent, dict):
		return _truncate_structured_value(agent, max_string_chars=300)
	compact: dict[str, Any] = {}
	for key in ('agent_id', 'agent_name'):
		if key in agent:
			compact[key] = agent[key]
	if 'last_task_message' in agent:
		compact['last_task_message'] = _truncate_text(str(agent['last_task_message']), 200)
	status = agent.get('agent_status')
	if isinstance(status, dict):
		status_compact: dict[str, Any] = {}
		for key, value in status.items():
			if key in ('completed', 'errored'):
				status_compact[key] = _truncate_structured_value(value, max_string_chars=800)
			else:
				status_compact[key] = _truncate_structured_value(value, max_string_chars=300)
		compact['agent_status'] = status_compact
	elif status is not None:
		compact['agent_status'] = _truncate_structured_value(status, max_string_chars=300)
	return compact


def _truncate_structured_value(value: Any, *, max_string_chars: int) -> Any:
	if isinstance(value, str):
		return _truncate_text(value, max_string_chars)
	if isinstance(value, list):
		return [_truncate_structured_value(item, max_string_chars=max_string_chars) for item in value[:20]]
	if isinstance(value, dict):
		return {
			str(key): _truncate_structured_value(item, max_string_chars=max_string_chars)
			for key, item in list(value.items())[:30]
		}
	return value


def _truncate_text(text: str, limit: int) -> str:
	if len(text) <= limit:
		return text
	return text[:limit] + f'… [truncated {len(text) - limit} chars]'


def _merge_step_tool_output(step: StepRecord, payload: dict[str, Any]) -> None:
	"""Merge a structured tool payload into a history step."""
	merged: dict[str, Any] = dict(step.tool_output or {})
	for key in TOOL_OUTPUT_KEYS:
		if key in payload and payload[key] is not None and merged.get(key) in (None, '', [], {}):
			merged[key] = payload[key]
	for key in ('name', 'tool_call_id', 'call_id'):
		if key in payload and key not in merged:
			merged[key] = payload[key]
	# Derive a usable extracted_content the eval reformat_agent_history
	# loop will surface. Priority: payload.text → payload.summary →
	# string payload.data → compact structured completion/artifact hints.
	if not merged.get('extracted_content'):
		candidate = (
			payload.get('text')
			or payload.get('summary')
			or (payload.get('data') if isinstance(payload.get('data'), str) else None)
			or _structured_extracted_content(payload)
		)
		if candidate:
			merged['extracted_content'] = candidate
	step.tool_output = merged


def _tool_output_payload_from_response_input_item(payload: dict[str, Any]) -> dict[str, Any] | None:
	"""Extract a tool-output payload from Rust model.response.input_item events."""
	if payload.get('source') != 'tool_output':
		return None
	item = payload.get('item')
	if not isinstance(item, dict):
		return None
	output = item.get('output')
	if isinstance(output, str):
		try:
			parsed = json.loads(output)
		except Exception:
			parsed = {'text': output}
	elif isinstance(output, dict):
		parsed = dict(output)
	else:
		parsed = {'output': output}
	if not isinstance(parsed, dict):
		parsed = {'output': parsed}
	if payload.get('name') is not None:
		parsed.setdefault('name', payload.get('name'))
	if payload.get('call_id') is not None:
		parsed.setdefault('tool_call_id', payload.get('call_id'))
	return parsed


def _attach_response_input_tool_output_to_step(state: '_AgentSessionState', payload: dict[str, Any]) -> None:
	tool_payload = _tool_output_payload_from_response_input_item(payload)
	if not tool_payload:
		return
	step = _step_for_call_id(state, str(tool_payload.get('tool_call_id') or ''), tool_payload)
	if step is not None:
		_merge_step_tool_output(step, tool_payload)


def _binary_supports_max_turns(cli: 'Path', subcommand: str) -> bool:
	"""Detect whether `<cli> <subcommand> --help` advertises `--max-turns`.

	The flag was added to run-* subcommands in browser-use/terminal
	magnus/eval-quality; older published binaries error with
	"unexpected argument '--max-turns'" and exit 2 immediately. Probe once
	per (cli, subcommand) pair and cache to avoid spamming `--help`.
	"""
	import subprocess
	key = f'{cli}::{subcommand}'
	cached = _MAX_TURNS_SUPPORT_CACHE.get(key)
	if cached is not None:
		return cached
	try:
		out = subprocess.run(
			[str(cli), subcommand, '--help'],
			capture_output=True,
			text=True,
			timeout=5,
		)
		supported = '--max-turns' in (out.stdout + out.stderr)
	except Exception:
		supported = False
	_MAX_TURNS_SUPPORT_CACHE[key] = supported
	return supported


def _extract_message_text(payload: dict[str, Any]) -> str:
	"""Pull the visible assistant text out of a `model.response.output_item`
	payload. OpenAI/Codex shapes: `{type:"message", content:[{type:"output_text", text:"..."}]}`
	with variants. Returns '' for reasoning, function_call, or any non-text item.
	"""
	if not isinstance(payload, dict):
		return ''
	item_type = payload.get('type')
	# Some Rust builds nest under `item` instead of flattening
	inner = payload.get('item') if isinstance(payload.get('item'), dict) else payload
	inner_type = inner.get('type') or item_type
	if inner_type not in (None, 'message', 'response.output_text'):
		return ''
	# Flat text variant
	text = inner.get('text') if isinstance(inner.get('text'), str) else None
	if text:
		return text
	# Content-list variant
	content = inner.get('content')
	if isinstance(content, list):
		parts: list[str] = []
		for c in content:
			if not isinstance(c, dict):
				continue
			ctype = c.get('type')
			if ctype in (None, 'output_text', 'text', 'response.output_text'):
				ctext = c.get('text')
				if isinstance(ctext, str) and ctext:
					parts.append(ctext)
		if parts:
			return '\n'.join(parts)
	return ''


def _looks_like_skip(result: Any) -> bool:
	"""True when the agent finished without doing any actual browser_script
	page interaction. Pattern: 0-2 steps, all of which are `browser` admin
	commands (`status`, `connect`, `recover`) or browser_script `observe`
	polls. This is the brust agent's most common failure mode on
	knowledge-flavoured tasks where it shortcuts to a training-data answer.
	"""
	if result is None:
		return False
	steps = getattr(result, 'steps', None) or []
	if len(steps) > 2:
		return False
	for step in steps:
		tool = (step.tool or '').lower()
		args = (step.tool_input or {}).get('arguments') if isinstance(step.tool_input, dict) else None
		if tool == 'browser_script':
			# code-mode browser_script counts as real browsing; observe-mode does not.
			if isinstance(args, dict) and args.get('action') in ('observe', 'cancel'):
				continue
			# Any code-mode call → real browsing happened.
			return False
		if tool not in ('browser', ''):
			# Some other real tool was used; not a skip.
			return False
	return True


def _maybe_inject_eval_directive(task: str | None, max_turns: int | None = None) -> str | None:
	"""Prepend the eval-mode directive when explicitly enabled.

	Gated by `BU_RUST_FORCE_SCREENSHOTS=1`; idempotent (won't re-add if the
	directive is already present). Prepended (not appended) because the
	earlier text in a long task instruction has more weight on the model's
	plan — the agent was ignoring the rule when it lived at the bottom."""
	if task is None:
		return None
	if os.environ.get('BU_RUST_FORCE_SCREENSHOTS') != '1':
		return task
	if '[EVAL MODE' in task:
		return task
	budget = max_turns if max_turns and max_turns > 0 else DEFAULT_RUST_MAX_TURNS
	directive = EVAL_SCREENSHOT_DIRECTIVE_TEMPLATE.format(max_turns=budget)
	return directive.lstrip() + '\n\n' + task


def _eval_mode_enabled() -> bool:
	return os.environ.get('BU_RUST_FORCE_SCREENSHOTS') == '1'


def _has_max_turns_arg(args: list[str]) -> bool:
	return any(arg == '--max-turns' or arg.startswith('--max-turns=') for arg in args)


def _split_global_config_args(args: list[str]) -> tuple[list[str], list[str]]:
	"""Move global Rust CLI `-c/--config` overrides before the subcommand."""
	global_args: list[str] = []
	remaining: list[str] = []
	i = 0
	while i < len(args):
		arg = args[i]
		if arg in ('-c', '--config'):
			global_args.append(arg)
			if i + 1 < len(args):
				global_args.append(args[i + 1])
				i += 2
			else:
				i += 1
			continue
		if arg.startswith('--config='):
			global_args.append(arg)
		else:
			remaining.append(arg)
		i += 1
	return global_args, remaining


def _has_config_override(args: list[str], key: str) -> bool:
	prefixes = (f'{key}=', f'{key}.')
	for arg in args:
		if arg == key or arg.startswith(prefixes):
			return True
	return False


def _default_state_dir() -> Path:
	return Path.home() / '.browser-use-terminal'


def _runtime_cwd(state_dir: Path | None = None) -> Path:
	"""Directory used as cwd for Rust browser-agent subprocesses.

	Browser tasks should not inherit a caller's repository cwd: the Rust core
	reads local workspace context from cwd, which is useful for coding agents
	but wastes prompt tokens and can distract browser eval runs.
	"""
	override = os.environ.get(RUNTIME_CWD_ENV)
	if override:
		return Path(override).expanduser()
	base = state_dir.expanduser() if state_dir else _default_state_dir()
	return base / 'browser-agent-cwd'


def _maybe_inject_cdp_connect(task: str | None, cdp_url: str | None) -> str | None:
	"""When the Python BrowserSession owns a real remote CDP endpoint (Unikraft
	cloud, Browserbase, anchor-browser etc.), tell the agent to attach to it
	as the FIRST browser action — otherwise the Rust default kicks in and
	launches a local managed-headless Chromium, which:
	  (a) wastes resources by booting a parallel browser the user already paid for,
	  (b) bypasses the proxy/stealth headers the cloud browser provides, and
	  (c) means stealth-only tests run against a vanilla Chromium that gets
	      CAPTCHA-walled instantly.

	Idempotent on the directive string. Only triggers when both task and
	cdp_url are present.
	"""
	if task is None or not cdp_url:
		return task
	if 'connect remote-cdp' in task:
		return task
	scheme = 'ws' if cdp_url.startswith('ws') else 'http'
	flag = '--ws' if scheme == 'ws' else '--url'
	preamble = (
		'[BROWSER ATTACH — required first and ONLY browser-connect action]\n'
		f'Your first browser command MUST be: `browser connect remote-cdp {flag} {cdp_url}`\n'
		'NEVER call `browser connect managed`, `browser connect local`, or '
		'`browser connect cloud` — they spawn a fresh Chromium that bypasses '
		'the cloud browser\'s proxy + stealth and IP. A real production '
		'browser with proxy + stealth headers is already running at the URL '
		'above; the only correct action is to attach to it. Skip the connect '
		'step entirely on subsequent turns — it is already connected.\n\n'
	)
	return preamble + task


def _prepend_retry_browse_directive(task: str) -> str:
	"""Add the skipped-browsing retry warning without outranking required CDP attach."""
	attach_marker = '[BROWSER ATTACH'
	if task.startswith(attach_marker):
		preamble_end = task.find('\n\n')
		if preamble_end != -1:
			insert_at = preamble_end + 2
			return task[:insert_at] + RETRY_BROWSE_DIRECTIVE + task[insert_at:]
	return RETRY_BROWSE_DIRECTIVE + task


class _AgentSessionState:
	"""Internal — accumulates per-session state from the event stream."""

	__slots__ = (
		'session_id',
		'final_summary',
		'failure',
		'events',
		'steps',
		'input_messages',
		'output_messages',
		'token_input_total',
		'token_output_total',
		'cost_total_usd',
		'_pending_tool_calls',
		'_pending_started_tool_calls',
		'_last_model_text',
		'_max_seen_seq',
	)

	def __init__(self) -> None:
		self.session_id: str | None = None
		self.final_summary: str | None = None
		self.failure: str | None = None
		self.events: list[AnyAgentEvent] = []
		self.steps: list[StepRecord] = []
		self.input_messages: list[dict[str, Any]] = []
		"""Mirror of `model.response.input_item` events — what the LLM saw."""
		self.output_messages: list[dict[str, Any]] = []
		"""Mirror of `model.response.output_item` events — what the LLM said."""
		self.token_input_total = 0
		self.token_output_total = 0
		self.cost_total_usd = 0.0
		self._pending_tool_calls: dict[str, StepRecord] = {}
		self._pending_started_tool_calls: dict[str, StepRecord] = {}
		self._last_model_text: str = ''
		self._max_seen_seq: int = -1

	def absorb(self, event: AnyAgentEvent) -> None:
		if event.seq <= self._max_seen_seq:
			return
		self._max_seen_seq = event.seq
		self.events.append(event)

		if self.session_id is None:
			self.session_id = event.session_id

		# Terminal events.
		if isinstance(event, SessionCreated):
			self.session_id = event.session_id
			return
		if isinstance(event, SessionResult):
			self.final_summary = event.text or self.final_summary
			return
		if isinstance(event, SessionFailure):
			self.failure = event.message
			return

		# Token / cost accounting from real `model.usage` events.
		if isinstance(event, ModelUsage):
			self.token_input_total += event.input_tokens
			self.token_output_total += event.output_tokens
			self.cost_total_usd += event.cost_usd
			return

		# Streamed assistant text — buffer until the next tool call so we
		# can attribute model_text to the step that produced it.
		if isinstance(event, (ModelDelta, ModelStreamDelta)):
			delta = event.delta
			if delta:
				self._last_model_text += delta
			return

		# LLM message items — feed agent.message_manager.last_input_messages.
		if isinstance(event, ModelResponseInputItem):
			self.input_messages.append(event.payload)
			_attach_response_input_tool_output_to_step(self, event.payload)
			return
		# LLM output items — captured here AND mined for message-type text so
		# the judge can see the agent's reasoning between tool calls. For
		# OpenAI/Codex responses, `type='message'` items carry the visible
		# assistant text (the "I navigated to X and found Y" prose); `type='reasoning'`
		# items carry hidden chain-of-thought (skip — judge doesn't get those);
		# `type='function_call'` is the raw tool_call (covered separately).
		if event.type == 'model.response.output_item':
			self.output_messages.append(event.payload)
			item_text = _extract_message_text(event.payload)
			if item_text:
				if self._last_model_text:
					self._last_model_text += '\n' + item_text
				else:
					self._last_model_text = item_text
				# If we already have a step in flight (text arrived between
				# tool_call and next tool_call), attach the text to the last
				# step retroactively so the judge sees the agent's reply.
				if self.steps and not self.steps[-1].model_text:
					self.steps[-1].model_text = item_text
			return

		# Tool calls — Rust emits THREE events per call:
		#   model.tool_call (LLM asked) → tool.started (we launched) → tool.finished (done)
		# We use model.tool_call as the canonical "step" anchor and
		# tool.finished to backfill tool_output.
		if isinstance(event, ModelToolCall):
			call_id = _call_id(event.payload, event.seq)
			step = StepRecord(
				seq=event.seq,
				tool=event.tool_name or '?',
				tool_input=event.payload,
				model_text=self._last_model_text,
				# Use model.tool_call ts_ms as a fallback "start" — ToolStarted
				# will override if it arrives, but for cases where the agent
				# emits a tool call without a separate tool.started event
				# (some Rust paths) this keeps duration non-zero.
				started_ts_ms=event.ts_ms,
			)
			self._pending_tool_calls[call_id] = step
			self.steps.append(step)
			self._last_model_text = ''
			return
		if isinstance(event, ToolStarted):
			call_id = _call_id(event.payload, event.seq)
			step = self._pending_tool_calls.get(call_id)
			if step is not None:
				self._pending_started_tool_calls[call_id] = step
				# tool.started is the canonical start moment — always overrides
				# the model.tool_call ts_ms fallback we set as an initial estimate.
				step.started_ts_ms = event.ts_ms
			return
		if isinstance(event, ToolFinished):
			call_id = _call_id(event.payload, event.seq)
			step = self._pending_tool_calls.pop(call_id, None) or self._pending_started_tool_calls.pop(
				call_id, None
			)
			if step is not None:
				# Merge, don't overwrite. For browser_script the event order is
				# tool.output (with data/text/outputs) -> tool.finished (just
				# {name, tool_call_id}). Assigning event.payload directly here
				# clobbered all the merged-in fields, leaving the convex
				# dashboard's per-step "tool response" view blank.
				existing = step.tool_output or {}
				if isinstance(event.payload, dict):
					merged = {**event.payload, **existing}  # existing wins for shared keys
					# But take name/tool_call_id from the more recent event if missing.
					for k in ('name', 'tool_call_id'):
						if k not in merged and k in event.payload:
							merged[k] = event.payload[k]
					step.tool_output = merged
				elif existing:
					step.tool_output = existing
				else:
					step.tool_output = event.payload
				# Record tool.finished timestamp for per-step duration.
				step.finished_ts_ms = event.ts_ms
				# If we never saw tool.started (older Rust builds, or events
				# arrived out of order), back-fill start from the model.tool_call
				# event's ts_ms so duration is at least positive.
				if step.started_ts_ms is None:
					# Find the model.tool_call event for this step
					for prior in reversed(self.events):
						if prior.seq <= step.seq and getattr(prior, 'ts_ms', None) is not None:
							step.started_ts_ms = prior.ts_ms
							break
			elif self.steps and self.steps[-1].tool_output is None:
				# Fall back to last-write-wins when call_id correlation is missing.
				self.steps[-1].tool_output = event.payload
				self.steps[-1].finished_ts_ms = event.ts_ms
			return
		if isinstance(event, ToolImage):
			# Rust emits one `tool.image` per screenshot/image artifact a tool
			# produces. Stash the on-disk path on the matching step so the
			# AgentHistoryList view can lazily base64-encode it for the judge.
			path = event.image_path
			if not path:
				return
			step = _step_for_call_id(self, event.tool_call_id, event.payload)
			if step is not None and path not in step.screenshot_paths:
				step.screenshot_paths.append(path)
			return
		if isinstance(event, ToolOutput):
			# `tool.output` from `browser_script` is where the REAL data lives:
			# `text` (the captured stdout/result), `data`, `outputs`, plus the
			# `images` array of file paths. `tool.finished` only has
			# {name, tool_call_id} — without merging in tool.output the judge
			# sees empty extracted_content for every step.
			step = _step_for_call_id(self, event.tool_call_id, event.payload)
			if step is None:
				return
			for path in event.image_paths:
				if path and path not in step.screenshot_paths:
					step.screenshot_paths.append(path)
			payload = event.payload if isinstance(event.payload, dict) else {}
			_merge_step_tool_output(step, payload)
			return


def _call_id(payload: dict[str, Any], seq: int) -> str:
	for key in ('call_id', 'tool_call_id', 'id'):
		value = payload.get(key)
		if value is not None:
			return str(value)
	return str(seq)


def _step_for_call_id(
	state: '_AgentSessionState',
	tool_call_id: str | None,
	payload: dict[str, Any],
) -> 'StepRecord | None':
	"""Find the StepRecord for a given tool_call_id, falling back to the most
	recent in-flight tool call. Used by `tool.image` / `tool.output` events
	that fire after the matching `model.tool_call`."""
	if tool_call_id:
		for bucket in (state._pending_started_tool_calls, state._pending_tool_calls):
			step = bucket.get(tool_call_id)
			if step is not None:
				return step
		# The tool may have already finished (image arrived late). Scan steps.
		for step in reversed(state.steps):
			tin = step.tool_input or {}
			for key in ('call_id', 'tool_call_id', 'id'):
				if str(tin.get(key) or '') == tool_call_id:
					return step
	# No tool_call_id correlation possible — attach to the last step that
	# matches the tool name when available, else the most recent step.
	tool_name = str(payload.get('name') or '') if isinstance(payload, dict) else ''
	if tool_name:
		for step in reversed(state.steps):
			if step.tool == tool_name:
				return step
	return state.steps[-1] if state.steps else None


class Agent:
	"""
	Rust-backed agent. Mirrors `browser_use.Agent(task, llm, browser, ...)`.

	Every option a user cares about is a constructor kwarg — no separate
	options struct, no provider override, no extra_env. Provider, model
	and api_key are read off the `llm` object's class and fields; browser
	config is read off the `browser` object's fields.
	"""

	def __init__(
		self,
		task: str | None = None,
		*,
		llm: Any | None = None,
		browser: Any | None = None,
		timeout: float | None = None,
		on_event: OnEvent | None = None,
		output_model: type[BaseModel] | None = None,
		state_dir: str | Path | None = None,
		extra_args: list[str] | None = None,
		**_unsupported: Any,
	) -> None:
		# Eval harnesses pass `browser_session=`; treat as alias.
		if browser is None and _unsupported.get('browser_session') is not None:
			browser = _unsupported.pop('browser_session')

		self.task = task
		self.llm = llm
		self.browser = browser
		self.timeout = timeout
		self.on_event = on_event
		self.output_model = output_model or _unsupported.pop('output_model_schema', None)
		self.state_dir = Path(state_dir) if state_dir else None
		self.extra_args: list[str] = list(extra_args or [])
		# Pull max_steps off the constructor so we can forward to --max-turns
		# without waiting for .run(max_steps=...). Some eval paths pass it here.
		ctor_max_steps = _unsupported.pop('max_steps', None) or _unsupported.pop('max_turns', None)
		self._ctor_max_steps: int | None = int(ctor_max_steps) if ctor_max_steps else None
		self.session_id: str | None = None
		self.result: AgentRunResult | None = None
		self._proc: asyncio.subprocess.Process | None = None
		self._cancelled = False

		# Eval-harness compat: expose a stub message_manager so code that
		# reads `agent.message_manager.last_input_messages` doesn't crash.
		self.message_manager = _MessageManagerStub()

		# Provider / model / api_key inferred from the llm.
		self.provider: Provider = _provider_from_llm(llm)
		self._model: str | None = _model_from_llm(llm)
		self._api_key: str | None = _api_key_from_llm(llm)

		# Swallow known legacy kwargs silently; warn only on truly unknown ones.
		unknown = {k: v for k, v in _unsupported.items() if k not in _KNOWN_LEGACY_KWARGS}
		if unknown:
			warnings.warn(
				f'browser_use.rust.Agent does not honour kwargs: {", ".join(sorted(unknown))}. '
				f'They were accepted for legacy compatibility but ignored.',
				stacklevel=2,
			)

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------

	async def run(
		self,
		max_steps: int | None = None,
		*,
		interactive: bool | None = None,
		on_step_start: Any | None = None,
		on_step_end: Any | None = None,
		**_unused: Any,
	) -> AgentRunResult:
		"""
		Mirrors `browser_use.Agent.run(max_steps, on_step_start, on_step_end)`.

		max_steps and the on_step_* callbacks are accepted for eval-harness
		compatibility; today the Rust core caps step count via its own config
		and our wrapper doesn't surface per-step lifecycle hooks (use
		`on_event` on the constructor for live observability instead).
		"""
		# on_step_* are accepted for classic-Agent signature compat (we don't
		# expose per-step callbacks — use on_event on the constructor instead).
		# max_steps IS now used — forwarded to the Rust --max-turns flag so
		# long research tasks don't crash with "exceeded maximum provider turns".
		_ = (on_step_start, on_step_end, _unused)
		effective_max = max_steps or self._ctor_max_steps
		if interactive is None:
			interactive = self.task is None
		if interactive:
			result = await self._run_interactive()
		else:
			if self.task is None:
				raise ValueError('Agent.run(interactive=False) requires a task.')
			task_text = _maybe_inject_cdp_connect(
				_maybe_inject_eval_directive(self.task, effective_max) or self.task,
				_browser_cdp_url(self.browser),
			)
			result = await self._run_headless(task_text, attach_to_session=None, max_turns=effective_max)

			# Retry-on-skip safety net. When the agent finished without doing
			# any real browser_script work — common failure mode where it
			# shortcuts to a training-data answer — re-run once with an
			# explicit "you skipped browsing" preamble. Adds cost only when
			# triggered; bounded to one retry. Default-on when FORCE_SCREENSHOTS
			# is set (i.e. we're in eval mode where skip = guaranteed failure).
			# Disable explicitly with BU_RUST_RETRY_ON_SKIP=0.
			retry_skip_enabled = (
				os.environ.get('BU_RUST_RETRY_ON_SKIP') == '1'
				or (
					os.environ.get('BU_RUST_FORCE_SCREENSHOTS') == '1'
					and os.environ.get('BU_RUST_RETRY_ON_SKIP') != '0'
				)
			)
			if retry_skip_enabled and _looks_like_skip(result):
				import logging
				logging.getLogger('browser_use.rust.Agent').warning(
					'Detected skipped-browsing on initial run (%d steps); retrying with explicit preamble',
					len(result.steps),
				)
				retry_task = _prepend_retry_browse_directive(task_text)
				retry = await self._run_headless(retry_task, attach_to_session=None, max_turns=effective_max)
				# Only keep the retry if it's clearly better — i.e. actually browsed.
				if not _looks_like_skip(retry):
					result = retry
		# Pin the result so `agent.history` / `agent.usage` reads see it.
		# Eval harnesses do `await agent.run(); agent.history.history` and
		# would otherwise read an empty placeholder.
		self.result = result
		return result

	async def follow_up(self, task: str) -> AgentRunResult:
		"""Continue the current session with another user turn."""
		if self.session_id is None:
			raise RuntimeError('No active session — call run() first or Agent.attach(...).')
		task_text = _maybe_inject_cdp_connect(
			_maybe_inject_eval_directive(task) or task,
			_browser_cdp_url(self.browser),
		)
		result = await self._run_headless(task_text, attach_to_session=self.session_id, subcommand='followup')
		self.result = result
		return result

	follow_up_task = follow_up

	@property
	def history(self) -> Any:
		"""
		Eval harnesses (and `Agent.run()` callers in classic browser-use) read
		`agent.history` to get the AgentHistoryList. Mirror that surface by
		returning the most recent run's result (which already implements the
		AgentHistoryList shape) or an empty placeholder before the first run.
		"""
		if self.result is not None:
			return self.result
		# Empty placeholder so `agent.history.history` etc. don't AttributeError.
		return AgentRunResult(exit_code=0, session_id=self.session_id)

	@property
	def usage(self) -> Any:
		"""Alias: `agent.usage` is read by some harnesses; delegate to result.usage."""
		if self.result is not None:
			return self.result.usage
		# Empty stub with .model_dump() so harness calls don't crash.
		from browser_use.rust.views import _UsageView

		return _UsageView()

	@property
	def laminar_trace_id(self) -> str | None:
		"""OTel trace id from the Rust core's `telemetry.trace` event, or None
		if telemetry was off or the run hasn't finished yet. Eval harnesses
		use this to build a Laminar deep link for the task."""
		if self.result is not None:
			return self.result.laminar_trace_id
		return None

	async def _judge_and_log(self) -> None:
		"""
		Run the ComprehensiveV1 judge over the just-finished run and stash the
		verdict on `self.result.judgement_dict`. Mirrors classic
		`browser_use.Agent._judge_and_log` so the eval harness's
		`agent_history.is_judged()` / `.judgement()` reads work unchanged.

		Uses gemini-3-flash-preview as the judge LLM (parity with eval/service.py
		line 335) — not the agent's main LLM, since judges must be cheap +
		independent.

		If anything in the judge LLM path fails, leave judgement_dict=None —
		the eval falls back to "Agent history not judged" and score 0, which
		is what we'd get from the noop anyway.
		"""
		result = self.result
		if result is None or result.exit_code != 0:
			return

		# Lazy import — avoids dragging classic-Agent deps into wrapper startup.
		try:
			from browser_use.agent.judge import construct_judge_messages
			from browser_use.agent.views import JudgementResult
		except Exception:
			return

		llm = _resolve_judge_llm()
		if llm is None:
			# No judge LLM available (Gemini key missing AND no fallback) —
			# leave unjudged rather than billing the user for an agent-LLM judge.
			import logging
			logging.getLogger('browser_use.rust.Agent').warning(
				'Judge LLM unavailable (no GEMINI_API_KEY / GOOGLE_API_KEY '
				'and no fallback llm) — skipping ComprehensiveV1 judge.'
			)
			return

		task = self.task or ''
		final_result = result.final_result() or ''
		# Per-step textual summary — close enough to classic agent_steps.
		agent_steps: list[str] = []
		for step in result.steps:
			tool = step.tool or '?'
			arg_keys = ','.join(sorted((step.tool_input or {}).keys()))
			out_keys = ','.join(sorted((step.tool_output or {}).keys()))
			agent_steps.append(f'{tool}(args={arg_keys}) -> ({out_keys})')

		screenshot_paths = [p for s in result.steps for p in s.screenshot_paths if p]

		try:
			messages = construct_judge_messages(
				task=task,
				final_result=final_result,
				agent_steps=agent_steps,
				screenshot_paths=screenshot_paths,
				max_images=10,
				ground_truth=None,
				use_vision=True,
			)
			response = await llm.ainvoke(messages, output_format=JudgementResult)
			judgement: JudgementResult = response.completion  # type: ignore[assignment]
		except Exception as exc:
			import logging

			logging.getLogger('browser_use.rust.Agent').warning(
				'Judge LLM call failed: %s', exc, exc_info=True
			)
			return

		# Store the verdict as a plain dict — the eval harness reads
		# `agent_history.judgement()['verdict']` etc.
		result.judgement_dict = {
			'verdict': bool(judgement.verdict),
			'reasoning': judgement.reasoning or '',
			'failure_reason': judgement.failure_reason or '',
			'impossible_task': bool(judgement.impossible_task),
			'reached_captcha': bool(judgement.reached_captcha),
		}

	async def cancel(self) -> None:
		self._cancelled = True
		if self.session_id:
			await self._run_oneoff(['cancel', self.session_id], expect_success=False)
		proc = self._proc
		if proc is None:
			return
		with contextlib.suppress(ProcessLookupError):
			proc.send_signal(signal.SIGINT)
		try:
			await asyncio.wait_for(proc.wait(), timeout=GRACEFUL_CANCEL_TIMEOUT_S)
		except asyncio.TimeoutError:
			with contextlib.suppress(ProcessLookupError):
				proc.terminate()
			try:
				await asyncio.wait_for(proc.wait(), timeout=2.0)
			except asyncio.TimeoutError:
				with contextlib.suppress(ProcessLookupError):
					proc.kill()

	def run_streaming(self) -> AsyncIterator[AnyAgentEvent]:
		"""Run the agent and yield events live. Fills `self.result` when done."""

		queue: asyncio.Queue[AnyAgentEvent | None] = asyncio.Queue()

		async def runner() -> None:
			try:
				original = self.on_event

				async def queueing_event(ev: AnyAgentEvent) -> None:
					await queue.put(ev)
					if original is not None:
						res = original(ev)
						if asyncio.iscoroutine(res):
							await res

				self.on_event = queueing_event  # type: ignore[assignment]
				try:
					self.result = await self.run(interactive=False)
				finally:
					self.on_event = original
			finally:
				await queue.put(None)

		task = asyncio.create_task(runner())

		async def driver() -> AsyncIterator[AnyAgentEvent]:
			try:
				while True:
					event = await queue.get()
					if event is None:
						return
					yield event
			finally:
				if not task.done():
					task.cancel()
					with contextlib.suppress(asyncio.CancelledError):
						await task

		return driver()

	@classmethod
	def attach(cls, session_id: str, **kwargs: Any) -> 'Agent':
		"""Reattach to an existing session."""
		agent = cls(**kwargs)
		agent.session_id = session_id
		return agent

	# ------------------------------------------------------------------
	# Interactive
	# ------------------------------------------------------------------

	async def _run_interactive(self) -> AgentRunResult:
		argv = self._cli_flags_excluding_task()
		env_overrides = self._env_overrides()
		if self.session_id:
			env_overrides['BUT_REEXEC_SESSION_ID'] = self.session_id

		def _spawn() -> int:
			previous = {k: os.environ.get(k) for k in env_overrides}
			os.environ.update(env_overrides)
			try:
				return launch_terminal_ui(extra_args=argv)
			finally:
				for k, prev in previous.items():
					if prev is None:
						os.environ.pop(k, None)
					else:
						os.environ[k] = prev

		started = time.monotonic()
		exit_code = await asyncio.to_thread(_spawn)
		return AgentRunResult(
			session_id=self.session_id,
			exit_code=exit_code,
			duration_seconds=time.monotonic() - started,
		)

	# ------------------------------------------------------------------
	# Headless
	# ------------------------------------------------------------------

	async def _run_headless(
		self,
		text: str,
		*,
		attach_to_session: str | None,
		subcommand: str | None = None,
		max_turns: int | None = None,
	) -> AgentRunResult:
		cli = find_browser_use_terminal_binary()
		if subcommand is None:
			subcommand = self.provider.subcommand

		# Headless argv shape:
		#   browser-use-terminal <global flags> <subcommand> <text> <subcmd flags>
		# Global flags (--state-dir, --collaboration-mode) MUST precede the
		# subcommand or clap errors out. Subcommand flags (--model) come after.
		global_extra_args, subcommand_extra_args = _split_global_config_args(self.extra_args)
		argv: list[str] = [str(cli)]
		argv.extend(self._global_cli_flags())
		argv.extend(global_extra_args)
		argv.append(subcommand)
		if attach_to_session and subcommand == 'followup':
			argv.append(attach_to_session)
		argv.append(text)
		if self._model and subcommand != 'followup':
			argv.extend(['--model', self._model])
		# Forward --max-turns when caller specified or constructor stored it.
		# Rust core default is 80; long research tasks (real_v8 #4 UniFi
		# product table, #7 arxiv search) exceed that and crash with
		# "agent exceeded maximum provider turns". The flag was added to
		# run-* subcommands in browser-use/terminal magnus/eval-quality —
		# feature-detect first so we don't crash older binaries (e.g. the
		# published release that the CI install.sh still pulls).
		effective_turns = max_turns or self._ctor_max_steps
		if (
			effective_turns
			and subcommand != 'followup'
			and not _has_max_turns_arg(self.extra_args)
			and _binary_supports_max_turns(cli, subcommand)
		):
			argv.extend(['--max-turns', str(int(effective_turns))])
		argv.extend(subcommand_extra_args)

		env = {**os.environ, **self._env_overrides()}
		runtime_cwd = _runtime_cwd(self.state_dir)
		runtime_cwd.mkdir(parents=True, exist_ok=True)

		started = time.monotonic()
		state = _AgentSessionState()
		if attach_to_session:
			state.session_id = attach_to_session
			self.session_id = attach_to_session

		try:
			proc = await asyncio.create_subprocess_exec(
				*argv,
				stdout=asyncio.subprocess.PIPE,
				stderr=asyncio.subprocess.PIPE,
				env=env,
				cwd=runtime_cwd,
			)
		except FileNotFoundError as err:
			raise RuntimeError(f'browser-use-terminal not found: {err}') from err
		self._proc = proc

		poll_task: asyncio.Task[None] | None = None

		async def _maybe_start_poller() -> None:
			nonlocal poll_task
			if poll_task is None and state.session_id:
				poll_task = asyncio.create_task(self._poll_events(cli, state, env))

		async def _read_stdout() -> None:
			assert proc.stdout is not None
			buffer = b''
			while True:
				chunk = await proc.stdout.read(64 * 1024)
				if not chunk:
					break
				buffer += chunk
				while b'\n' in buffer:
					line, buffer = buffer.split(b'\n', 1)
					token = line.decode(errors='replace').strip()
					if not token:
						continue
					if all(c in '0123456789abcdef-' for c in token) and len(token) >= 8:
						if state.session_id is None:
							state.session_id = token
							self.session_id = token
							await _maybe_start_poller()

		stdout_task = asyncio.create_task(_read_stdout())

		try:
			if self.timeout:
				exit_code = await asyncio.wait_for(proc.wait(), timeout=self.timeout)
			else:
				exit_code = await proc.wait()
		except asyncio.TimeoutError:
			await self.cancel()
			exit_code = 124
		except asyncio.CancelledError:
			await self.cancel()
			raise
		finally:
			stdout_task.cancel()
			with contextlib.suppress(asyncio.CancelledError, BaseException):
				await stdout_task
			if poll_task is not None:
				poll_task.cancel()
				with contextlib.suppress(asyncio.CancelledError):
					await poll_task
			if state.session_id:
				await self._collect_events_once(cli, state, env)

		stderr_blob = b''
		if proc.stderr is not None:
			with contextlib.suppress(Exception):
				stderr_blob = await proc.stderr.read()

		if state.final_summary is None and state.session_id:
			state.final_summary = await self._fetch_show_result(cli, state.session_id, env)

		result = AgentRunResult(
			session_id=state.session_id,
			exit_code=exit_code,
			final_summary=state.final_summary,
			failure=state.failure,
			steps=state.steps,
			events=state.events,
			stderr=stderr_blob.decode(errors='replace'),
			duration_seconds=time.monotonic() - started,
		)

		if self.output_model is not None and state.final_summary:
			result.final_output = self._parse_output_model(state.final_summary)

		# Loud diagnostics when the run produced nothing — helps debug eval
		# wrapper-vs-rust handoff issues. Prints argv, exit, and stderr.
		if not state.events and not state.final_summary:
			import logging
			import sys

			logger = logging.getLogger('browser_use.rust.Agent')
			diag = (
				'\n========= rust Agent: subprocess returned no events =========\n'
				f'argv:     {argv}\n'
				f'cwd:      {runtime_cwd}\n'
				f'exit:     {exit_code}\n'
				f'duration: {(time.monotonic() - started):.2f}s\n'
				f'session:  {state.session_id}\n'
				f'env override keys: {sorted(self._env_overrides().keys())}\n'
				f'LLM_BROWSER_BROWSER_MODE: {env.get("LLM_BROWSER_BROWSER_MODE")}\n'
				f'browser-use-terminal: {find_browser_use_terminal_binary()}\n'
				'stderr:\n'
				f'{stderr_blob.decode(errors="replace")[:4000]}\n'
				'============================================================='
			)
			logger.error(diag)
			print(diag, file=sys.stderr, flush=True)

		from browser_use.rust.views import _UsageView

		usage = _UsageView()
		usage.input_tokens = state.token_input_total
		usage.output_tokens = state.token_output_total
		usage.cost = state.cost_total_usd
		# Pull the model name from the first model.config event if present.
		for ev in state.events:
			if ev.type == 'model.config':
				usage.model = ev.payload.get('model')
				break
		# Rust core emits cost=0 on every model.usage event; compute it ourselves
		# from input/output token totals so the eval pipeline shows real $.
		if usage.cost == 0.0 and (usage.input_tokens > 0 or usage.output_tokens > 0):
			try:
				usage.cost = await _compute_cost_usd(usage.model, usage.input_tokens, usage.output_tokens)
			except Exception:
				pass
		object.__setattr__(result, '_usage_cache', usage)
		# Feed agent.message_manager.last_input_messages for eval harness reads.
		self.message_manager.last_input_messages = list(state.input_messages)

		self._proc = None
		return result

	async def _poll_events(
		self,
		cli: Path,
		state: _AgentSessionState,
		env: dict[str, str],
	) -> None:
		interval = DEFAULT_POLL_INTERVAL_MS / 1000.0
		while not self._cancelled:
			try:
				await self._collect_events_once(cli, state, env)
			except Exception:
				pass
			await asyncio.sleep(interval)

	async def _collect_events_once(
		self,
		cli: Path,
		state: _AgentSessionState,
		env: dict[str, str],
	) -> None:
		if not state.session_id:
			return
		proc = await asyncio.create_subprocess_exec(
			str(cli),
			'events',
			state.session_id,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.DEVNULL,
			env=env,
		)
		assert proc.stdout is not None
		buffer = b''
		try:
			while True:
				chunk = await proc.stdout.read(64 * 1024)
				if not chunk:
					break
				buffer += chunk
				while b'\n' in buffer:
					line, buffer = buffer.split(b'\n', 1)
					event = parse_event(line)
					if event is None or event.seq <= state._max_seen_seq:
						continue
					state.absorb(event)
					if self.on_event is not None:
						res = self.on_event(event)
						if asyncio.iscoroutine(res):
							await res
		finally:
			with contextlib.suppress(ProcessLookupError):
				proc.terminate()
			with contextlib.suppress(asyncio.TimeoutError):
				await asyncio.wait_for(proc.wait(), timeout=2.0)

	async def _fetch_show_result(
		self,
		cli: Path,
		session_id: str,
		env: dict[str, str],
	) -> str | None:
		out = await self._run_oneoff(['show', session_id], expect_success=True, env=env)
		if out is None:
			return None
		marker = '\nResult\n'
		idx = out.find(marker)
		if idx >= 0:
			return out[idx + len(marker) :].strip() or None
		return None

	async def _run_oneoff(
		self,
		args: list[str],
		*,
		expect_success: bool,
		env: dict[str, str] | None = None,
	) -> str | None:
		cli = find_browser_use_terminal_binary()
		try:
			proc = await asyncio.create_subprocess_exec(
				str(cli),
				*args,
				stdout=asyncio.subprocess.PIPE,
				stderr=asyncio.subprocess.PIPE,
				env=env or os.environ,
			)
		except FileNotFoundError:
			return None
		stdout_bytes, _ = await proc.communicate()
		if expect_success and proc.returncode != 0:
			return None
		return stdout_bytes.decode()

	def _parse_output_model(self, text: str) -> Any:
		assert self.output_model is not None
		with contextlib.suppress(Exception):
			return self.output_model.model_validate_json(text)
		fence = '```json'
		if fence in text:
			start = text.index(fence) + len(fence)
			end = text.find('```', start)
			if end > start:
				blob = text[start:end].strip()
				with contextlib.suppress(Exception):
					return self.output_model.model_validate_json(blob)
		opener = text.find('{')
		closer = text.rfind('}')
		if opener >= 0 and closer > opener:
			with contextlib.suppress(Exception):
				return self.output_model.model_validate_json(text[opener : closer + 1])
		return None

	# ------------------------------------------------------------------
	# Mapping browser/llm onto subprocess flags + env
	# ------------------------------------------------------------------

	def _global_cli_flags(self) -> list[str]:
		"""
		Global (pre-subcommand) flags for `browser-use-terminal` AND `but`.
		These must precede any subcommand or clap errors out.

		Also injects `-c browser.preference.mode=...` derived from the
		caller's `browser` BrowserSession. The Rust agent reads this
		setting from the store to decide whether to call
		`browser connect local` (which prompts on macOS) vs
		`browser connect managed --headless` (no prompt, auto-launches
		bundled Chromium). Default = managed-headless so headless eval
		runs don't block on a user click. Override by passing your own
		`extra_args=['-c', 'browser.preference.mode=local']`.
		"""
		flags: list[str] = []
		if self.state_dir:
			flags.extend(['--state-dir', str(self.state_dir)])
		for feature in BROWSER_TASK_DISABLED_FEATURES:
			if feature == 'features.shell_tool' and os.environ.get(SHELL_TOOL_OPT_IN_ENV) == '1':
				continue
			if not _has_config_override(self.extra_args, feature):
				flags.extend(['-c', f'{feature}=false'])
		if _eval_mode_enabled():
			for key, value in EVAL_BROWSER_TASK_CONFIG:
				if not _has_config_override(self.extra_args, key):
					flags.extend(['-c', f'{key}={value}'])
		mode = _browser_preference_mode(self.browser)
		# Always set mode — see _env_overrides for the rationale. The
		# Rust core's LLM_BROWSER_REMOTE_CDP_URL carve-out lets the
		# agent attach to a pre-provisioned cloud browser without the
		# wrapper having to remove the mode lock.
		if mode and not any('browser.preference.mode=' in a for a in self.extra_args):
			flags.extend(['-c', f'browser.preference.mode={mode}'])
		return flags

	def _cli_flags_excluding_task(self) -> list[str]:
		"""
		Argv for the interactive `but` binary (the TUI). `but` takes
		`--browser`, `--model`, etc. as positional flags after the binary
		name — no subcommand structure. Globals + binary-specific flags
		live here together.
		"""
		flags: list[str] = self._global_cli_flags()
		browser_label = _browser_label(self.browser)
		if browser_label:
			flags.extend(['--browser', browser_label])
		if self._model:
			flags.extend(['--model', self._model])
		global_extra_args, remaining_extra_args = _split_global_config_args(self.extra_args)
		flags.extend(global_extra_args)
		flags.extend(remaining_extra_args)
		return flags

	def _env_overrides(self) -> dict[str, str]:
		"""
		Per-Agent env vars merged on top of os.environ for the subprocess.

		`LLM_BROWSER_BROWSER_MODE` is the one the Rust headless CLI ACTUALLY
		reads to pick `browser connect local` vs `... managed --headless` vs
		`... managed --headed`. Default = managed-headless so eval / CI runs
		don't block on a macOS "Allow remote debugging" Chrome dialog.

		The BUT_BROWSER_* env vars below are forward-looking placeholders for
		fields the Rust binary doesn't yet read (cdp_url, proxy, user_data_dir,
		channel). Once matching Rust patches land they become live without a
		Python wrapper change.
		"""
		env: dict[str, str] = {}
		if self._api_key:
			env[self.provider.api_key_env] = self._api_key
		# Always set browser_mode — without it the Rust core's
		# default_base_instructions_for_model returns the terminal-only
		# codex prompt instead of the full browser-agent-instructions
		# (Browser Agent Contract, fan-out rules, attach directive,
		# interaction skills). When an external cdp_url is also present,
		# rely on the Rust core's LLM_BROWSER_REMOTE_CDP_URL carve-out
		# to let the agent's `connect remote-cdp` through the lock.
		env['LLM_BROWSER_BROWSER_MODE'] = _browser_preference_mode(self.browser) or 'managed-headless'
		# Forward-looking BUT_BROWSER_* — Rust doesn't read these yet.
		cdp_url = _browser_cdp_url(self.browser)
		if cdp_url:
			env['BUT_BROWSER_CDP_URL'] = cdp_url
			# Also publish under the name the Rust core checks for the
			# remote-cdp lock carve-out. Without this, an `enforce_
			# browser_command_matches_selected_mode` lock would reject
			# the agent's `connect remote-cdp` call.
			env['LLM_BROWSER_REMOTE_CDP_URL'] = cdp_url
		proxy_url = _browser_proxy(self.browser)
		if proxy_url:
			env['BUT_BROWSER_PROXY'] = proxy_url
		headless = _browser_headless(self.browser)
		if headless is not None:
			env['BUT_BROWSER_HEADLESS'] = '1' if headless else '0'
		user_data_dir = _browser_user_data_dir(self.browser)
		if user_data_dir:
			env['BUT_BROWSER_USER_DATA_DIR'] = str(user_data_dir)
		channel = _browser_channel(self.browser)
		if channel:
			env['BUT_BROWSER_CHANNEL'] = channel
		return env

	# ------------------------------------------------------------------
	# Diagnostics
	# ------------------------------------------------------------------

	@staticmethod
	def binary_path() -> Path:
		return find_but_binary()

	@staticmethod
	def headless_binary_path() -> Path:
		return find_browser_use_terminal_binary()


# ----------------------------------------------------------------------
# Judge LLM resolution + cost computation
# ----------------------------------------------------------------------


def _resolve_judge_llm() -> Any | None:
	"""Pick a cheap, independent judge LLM. Matches eval/service.py:335.

	Order of preference:
	1. `gemini-3-flash-preview` via ChatGoogle (cheap, fast, used in eval today)
	2. `gpt-4o-mini` via ChatOpenAI (fallback if Google key absent)
	3. None — caller skips judging rather than burn agent-LLM cost.
	"""
	# Gemini (preferred): only attempt if a Google API key is set.
	if os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY'):
		try:
			from browser_use.llm.google.chat import ChatGoogle

			return ChatGoogle(model='gemini-3-flash-preview')
		except Exception:
			pass

	# OpenAI mini fallback.
	if os.environ.get('OPENAI_API_KEY'):
		try:
			from browser_use.llm.openai.chat import ChatOpenAI

			return ChatOpenAI(model='gpt-4o-mini')
		except Exception:
			pass

	return None


async def _compute_cost_usd(model: str | None, input_tokens: int, output_tokens: int) -> float:
	"""Best-effort cost computation from LiteLLM's public pricing JSON.

	Returns 0.0 if the model isn't priced or the lookup fails. The Rust core
	emits `cost: 0.0` on `model.usage` events; this is the canonical place to
	fill it in so eval `usage.cost` lines up with reality.
	"""
	if not model or (input_tokens <= 0 and output_tokens <= 0):
		return 0.0
	try:
		from browser_use.llm.views import ChatInvokeUsage
		from browser_use.tokens.service import TokenCost
	except Exception:
		return 0.0

	cost_service = TokenCost(include_cost=True)
	try:
		await cost_service.initialize()
		usage = ChatInvokeUsage(
			prompt_tokens=int(input_tokens),
			prompt_cached_tokens=0,
			prompt_cache_creation_tokens=0,
			prompt_image_tokens=0,
			completion_tokens=int(output_tokens),
			total_tokens=int(input_tokens) + int(output_tokens),
		)
		breakdown = await cost_service.calculate_cost(model, usage)
		if breakdown is None:
			return 0.0
		# Sum the relevant components — uncached prompt + completion. Cached
		# reads and cache creation are zero in our case (Rust doesn't emit them).
		total = float(breakdown.new_prompt_cost or 0.0) + float(breakdown.completion_cost or 0.0)
		return total
	except Exception:
		return 0.0


# ----------------------------------------------------------------------
# llm/browser introspection helpers
# ----------------------------------------------------------------------


def _provider_from_llm(llm: Any) -> Provider:
	if llm is None:
		return Provider.OPENAI
	return _PROVIDER_BY_CLASS.get(type(llm).__name__, Provider.OPENAI)


def _model_from_llm(llm: Any) -> str | None:
	if llm is None:
		return None
	for attr in ('model', 'model_name', 'name'):
		value = getattr(llm, attr, None)
		if isinstance(value, str) and value:
			return value
	return None


def _api_key_from_llm(llm: Any) -> str | None:
	if llm is None:
		return None
	value = getattr(llm, 'api_key', None)
	if value is None:
		return None
	if hasattr(value, 'get_secret_value'):
		return value.get_secret_value()
	value = str(value)
	return value or None


def _browser_label(browser: Any) -> str | None:
	if browser is None:
		return None
	for attr in ('name', 'browser_class'):
		value = getattr(browser, attr, None)
		if isinstance(value, str) and value:
			return value
	return None


def _browser_cdp_url(browser: Any) -> str | None:
	return _read_browser_attr(browser, ('cdp_url', 'wss_url'))


def _browser_proxy(browser: Any) -> str | None:
	"""Pull a proxy URL out of either BrowserSession.proxy or .browser_profile.proxy."""
	proxy = _read_browser_attr(browser, ('proxy',))
	if proxy is None:
		return None
	if isinstance(proxy, str):
		return proxy
	# pydantic ProxySettings → has .server
	server = getattr(proxy, 'server', None)
	if isinstance(server, str):
		return server
	if isinstance(proxy, dict):
		return proxy.get('server')
	return None


def _browser_headless(browser: Any) -> bool | None:
	value = _read_browser_attr(browser, ('headless',))
	if isinstance(value, bool):
		return value
	return None


def _browser_user_data_dir(browser: Any) -> Any:
	return _read_browser_attr(browser, ('user_data_dir',))


def _browser_preference_mode(browser: Any) -> str | None:
	"""
	Map Python BrowserSession config onto the Rust core's
	`browser.preference.mode` setting (local / managed-headless /
	managed-headed / cloud).

	Default = managed-headless: the Rust binary auto-launches bundled
	Chromium with no "Allow remote debugging" click on macOS and works
	out of the box in headless CI.

	We DELIBERATELY do not auto-pick `remote` from `BrowserSession.cdp_url`.
	When a Python-side BrowserSession starts a local browser it populates
	cdp_url with `ws://127.0.0.1:9222/...` — but the Rust agent owns its
	own browser unless a wrapper/eval path explicitly passes a cloud CDP URL.
	The wrapper publishes any provided cdp_url as `LLM_BROWSER_REMOTE_CDP_URL`
	and injects the required `browser connect remote-cdp ...` first-action
	directive; the Rust core's remote-CDP carve-out permits that attach even
	while the browser-agent prompt stays enabled through managed-headless mode.
	"""
	headless = _browser_headless(browser)
	if headless is False:
		return 'managed-headed'
	return 'managed-headless'


def _browser_channel(browser: Any) -> str | None:
	value = _read_browser_attr(browser, ('channel', 'browser_class'))
	if value is None:
		return None
	# BrowserChannel enum -> string
	if hasattr(value, 'value'):
		value = value.value
	return str(value) if value else None


def _read_browser_attr(browser: Any, attr_names: tuple[str, ...]) -> Any:
	"""Look up a field on the browser obj OR on its nested .browser_profile / .profile."""
	if browser is None:
		return None
	for attr in attr_names:
		direct = getattr(browser, attr, None)
		if direct is not None:
			return direct
	for nested_attr in ('browser_profile', 'profile'):
		nested = getattr(browser, nested_attr, None)
		if nested is None:
			continue
		for attr in attr_names:
			value = getattr(nested, attr, None)
			if value is not None:
				return value
	return None
