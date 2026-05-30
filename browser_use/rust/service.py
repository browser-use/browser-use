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

OnEvent = Callable[[AnyAgentEvent], None] | Callable[[AnyAgentEvent], Awaitable[None]]


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
			return
		# (output items captured for completeness; not yet exposed to callers)
		if event.type == 'model.response.output_item':  # pragma: no cover
			self.output_messages.append(event.payload)
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
			return
		if isinstance(event, ToolFinished):
			call_id = _call_id(event.payload, event.seq)
			step = self._pending_tool_calls.pop(call_id, None) or self._pending_started_tool_calls.pop(
				call_id, None
			)
			if step is not None:
				step.tool_output = event.payload
			elif self.steps and self.steps[-1].tool_output is None:
				# Fall back to last-write-wins when call_id correlation is missing.
				self.steps[-1].tool_output = event.payload
			return


def _call_id(payload: dict[str, Any], seq: int) -> str:
	for key in ('call_id', 'tool_call_id', 'id'):
		value = payload.get(key)
		if value is not None:
			return str(value)
	return str(seq)


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
		# max_steps / on_step_* are no-ops here — accepted to match the
		# classic Agent.run signature. Document loudly when debugging.
		_ = (max_steps, on_step_start, on_step_end, _unused)
		if interactive is None:
			interactive = self.task is None
		if interactive:
			return await self._run_interactive()
		if self.task is None:
			raise ValueError('Agent.run(interactive=False) requires a task.')
		return await self._run_headless(self.task, attach_to_session=None)

	async def follow_up(self, task: str) -> AgentRunResult:
		"""Continue the current session with another user turn."""
		if self.session_id is None:
			raise RuntimeError('No active session — call run() first or Agent.attach(...).')
		return await self._run_headless(task, attach_to_session=self.session_id, subcommand='followup')

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
		from browser_use.rust.compat import _UsageView

		return _UsageView()

	async def _judge_and_log(self) -> None:
		"""
		No-op compatibility stub.

		The eval-internal harness calls this method when `judge_type ==
		'comprehensivev1'`. Classic browser_use.Agent didn't have it
		either (the harness hits AttributeError on stock browser-use).
		Providing a stub means the eval keeps running and the external
		judge stage handles scoring instead.
		"""
		return None

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
	) -> AgentRunResult:
		cli = find_browser_use_terminal_binary()
		if subcommand is None:
			subcommand = self.provider.subcommand

		# Headless argv shape:
		#   browser-use-terminal <global flags> <subcommand> <text> <subcmd flags>
		# Global flags (--state-dir, --collaboration-mode) MUST precede the
		# subcommand or clap errors out. Subcommand flags (--model) come after.
		argv: list[str] = [str(cli)]
		argv.extend(self._global_cli_flags())
		argv.append(subcommand)
		if attach_to_session and subcommand == 'followup':
			argv.append(attach_to_session)
		argv.append(text)
		if self._model and subcommand != 'followup':
			argv.extend(['--model', self._model])
		argv.extend(self.extra_args)

		env = {**os.environ, **self._env_overrides()}

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

		# Surface real token/cost numbers + the prompt messages for evals.
		from browser_use.rust.compat import _UsageView

		usage = _UsageView()
		usage.input_tokens = state.token_input_total
		usage.output_tokens = state.token_output_total
		usage.cost = state.cost_total_usd
		# Pull the model name from the first model.config event if present.
		for ev in state.events:
			if ev.type == 'model.config':
				usage.model = ev.payload.get('model')
				break
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
		mode = _browser_preference_mode(self.browser)
		# Honour any explicit mode the user already set via extra_args.
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
		flags.extend(self.extra_args)
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
		# Authoritative browser-mode lever. Read by browser-use-cli.
		env['LLM_BROWSER_BROWSER_MODE'] = _browser_preference_mode(self.browser) or 'managed-headless'
		# Forward-looking BUT_BROWSER_* — Rust doesn't read these yet.
		cdp_url = _browser_cdp_url(self.browser)
		if cdp_url:
			env['BUT_BROWSER_CDP_URL'] = cdp_url
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
	managed-headed / cloud / remote).

	Default = managed-headless: auto-launches bundled Chromium with no
	"Allow remote debugging" click on macOS. Set browser=BrowserSession()
	to get this; pass `headless=False` to switch to managed-headed.
	"""
	if _browser_cdp_url(browser):
		# Remote CDP — let the Rust binary attach to whatever's at that url.
		# (Pending matching --cdp-url flag Rust-side; setting the mode is
		# the contract.)
		return 'remote'
	headless = _browser_headless(browser)
	if headless is False:
		return 'managed-headed'
	# Default — including when `browser=None` — picks managed-headless so
	# eval / CI runs don't block on a macOS Chrome dialog.
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
