from __future__ import annotations

import asyncio
import inspect
import json
import os
import shutil
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Generic

from pydantic import BaseModel
from typing_extensions import TypeVar
from uuid_extensions import uuid7str

from browser_use.agent.views import ActionResult, AgentHistory, AgentHistoryList, AgentState, StepMetadata
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.views import BrowserStateHistory, TabInfo
from browser_use.tokens.views import ModelUsageStats, UsageSummary


AgentStructuredOutput = TypeVar('AgentStructuredOutput', bound=BaseModel)
AgentHookFunc = Callable[[Any], Awaitable[None] | None]
AgentDoneCallback = Callable[[AgentHistoryList], Awaitable[None] | None]


class RustAgentError(RuntimeError):
	"""Raised when the Rust terminal core cannot run a task."""


def find_browser_use_terminal_binary() -> str:
	"""Find the terminal binary used by the Rust-backed Browser Use Agent."""
	env_path = os.environ.get('BROWSER_USE_TERMINAL_BINARY')
	if env_path:
		return env_path
	path_binary = shutil.which('browser-use-terminal')
	if path_binary:
		return path_binary
	candidates = [
		Path.cwd() / 'target' / 'debug' / 'browser-use-terminal',
		Path.cwd().parent / 'terminal' / 'target' / 'debug' / 'browser-use-terminal',
		Path('/home/exedev/Developer/terminal/target/debug/browser-use-terminal'),
	]
	for candidate in candidates:
		if candidate.exists():
			return str(candidate)
	raise RustAgentError(
		'Could not find browser-use-terminal. Set BROWSER_USE_TERMINAL_BINARY or build the terminal CLI.'
	)


def _model_name(llm: Any | None) -> str:
	for attr in ('model', 'model_name', 'name'):
		value = getattr(llm, attr, None)
		if isinstance(value, str) and value:
			return value
	return os.environ.get('BROWSER_USE_RUST_MODEL', 'gpt-5.3-codex-spark')


def _extract_cdp_url(browser_session: BrowserSession | None) -> str | None:
	if browser_session is None:
		return None
	for attr in ('cdp_url',):
		value = getattr(browser_session, attr, None)
		if isinstance(value, str) and value:
			return value
	profile = getattr(browser_session, 'browser_profile', None)
	value = getattr(profile, 'cdp_url', None)
	if isinstance(value, str) and value:
		return value
	return None


def _initial_navigation_url(initial_actions: Any) -> str | None:
	if not isinstance(initial_actions, list):
		return None
	for action in initial_actions:
		if not isinstance(action, dict):
			continue
		for name, payload in action.items():
			if name in ('open_tab', 'go_to_url', 'navigate') and isinstance(payload, dict):
				url = payload.get('url')
				if isinstance(url, str) and url:
					return url
	return None


def _task_with_initial_navigation(task: str, initial_actions: Any) -> str:
	url = _initial_navigation_url(initial_actions)
	if not url:
		return task
	return f'First navigate to {url!r}, then complete the task.\n\n{task}'


def _task_with_schema(task: str, output_model_schema: type[BaseModel] | None) -> str:
	if output_model_schema is None:
		return task
	schema = json.dumps(output_model_schema.model_json_schema(), indent=2)
	return f'{task}\n\nExpected output JSON schema for the final answer:\n{schema}'


def _event_type(event: dict[str, Any]) -> str:
	return str(event.get('event_type') or event.get('type') or '')


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
	payload = event.get('payload')
	return payload if isinstance(payload, dict) else {}


def _result_from_events(events: list[dict[str, Any]]) -> str | None:
	for event in reversed(events):
		if _event_type(event) != 'session.done':
			continue
		payload = _event_payload(event)
		result = payload.get('result')
		if isinstance(result, str) and result.strip():
			return result.strip()
		result_file = payload.get('result_file_url') or payload.get('result_file_path') or payload.get('result_file')
		if isinstance(result_file, str) and result_file:
			return f'Saved result file.\n\nFile:\n{result_file}'
	return None


def _failure_from_events(events: list[dict[str, Any]]) -> str | None:
	for event in reversed(events):
		if _event_type(event) == 'session.failed':
			error = _event_payload(event).get('error')
			if isinstance(error, str) and error:
				return error
	return None


def _browser_state_from_events(events: list[dict[str, Any]]) -> BrowserStateHistory:
	url = ''
	title = ''
	tabs: list[TabInfo] = []
	for event in events:
		if _event_type(event) not in ('browser.connected', 'browser.reconnected', 'browser.target_changed', 'browser.page', 'browser.state'):
			continue
		payload = _event_payload(event)
		url = str(payload.get('url') or url)
		title = str(payload.get('title') or title)
		raw_tabs = payload.get('tabs')
		if isinstance(raw_tabs, list):
			next_tabs = []
			for idx, raw in enumerate(raw_tabs):
				if isinstance(raw, dict):
					next_tabs.append(
						TabInfo(
							url=str(raw.get('url') or ''),
							title=str(raw.get('title') or ''),
							target_id=str(raw.get('target_id') or raw.get('tab_id') or f'tab-{idx}'),
						)
					)
			if next_tabs:
				tabs = next_tabs
	if not tabs and (url or title):
		tabs = [TabInfo(url=url, title=title, target_id='tab-0')]
	return BrowserStateHistory(url=url, title=title, tabs=tabs, interacted_element=[])


def _usage_from_events(events: list[dict[str, Any]], model: str) -> UsageSummary:
	input_tokens = 0
	cached_input_tokens = 0
	output_tokens = 0
	cost = 0.0
	invocations = 0

	for event in events:
		if _event_type(event) != 'model.usage':
			continue
		payload = _event_payload(event)
		input_tokens += int(payload.get('input_tokens') or 0)
		cached_input_tokens += int(payload.get('input_cached_tokens') or payload.get('cached_input_tokens') or 0)
		output_tokens += int(payload.get('output_tokens') or 0)
		cost += float(payload.get('cost_usd') or payload.get('cost') or 0.0)
		invocations += 1

	total_tokens = input_tokens + output_tokens
	by_model = {
		model: ModelUsageStats(
			model=model,
			prompt_tokens=input_tokens,
			completion_tokens=output_tokens,
			total_tokens=total_tokens,
			cost=cost,
			invocations=invocations,
		)
	}
	return UsageSummary(
		total_prompt_tokens=input_tokens,
		total_prompt_cost=0.0,
		total_prompt_cached_tokens=cached_input_tokens,
		total_prompt_cached_cost=0.0,
		total_completion_tokens=output_tokens,
		total_completion_cost=0.0,
		total_tokens=total_tokens,
		total_cost=cost,
		entry_count=invocations,
		by_model=by_model,
	)


def _history_from_events(
	events: list[dict[str, Any]],
	*,
	model: str,
	started: float,
	finished: float,
	output_model_schema: type[AgentStructuredOutput] | None,
	process_error: str | None,
) -> AgentHistoryList[AgentStructuredOutput]:
	final_result = _result_from_events(events)
	failure = process_error or _failure_from_events(events)
	if final_result is None and failure is None:
		failure = 'Rust terminal session did not produce a final result.'
	is_done = final_result is not None and failure is None
	result = ActionResult(
		is_done=is_done,
		success=True if is_done else None,
		error=failure,
		extracted_content=final_result,
	)
	history = AgentHistory(
		model_output=None,
		result=[result],
		state=_browser_state_from_events(events),
		metadata=StepMetadata(step_start_time=started, step_end_time=finished, step_number=max(1, len(events))),
	)
	history_list: AgentHistoryList[AgentStructuredOutput] = AgentHistoryList(
		history=[history],
		usage=_usage_from_events(events, model),
	)
	history_list._output_model_schema = output_model_schema
	return history_list


class Agent(Generic[AgentStructuredOutput]):
	"""Browser Use-style Agent backed by the Rust browser-use-terminal core."""

	def __init__(
		self,
		task: str,
		llm: Any | None = None,
		browser_profile: BrowserProfile | None = None,
		browser_session: BrowserSession | None = None,
		browser: BrowserSession | None = None,
		tools: Any | None = None,
		controller: Any | None = None,
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		initial_actions: list[dict[str, dict[str, Any]]] | None = None,
		register_done_callback: AgentDoneCallback | None = None,
		register_external_agent_status_raise_error_callback: Callable[[], Awaitable[bool]] | None = None,
		register_should_stop_callback: Callable[[], Awaitable[bool]] | None = None,
		output_model_schema: type[AgentStructuredOutput] | None = None,
		injected_agent_state: AgentState | None = None,
		task_id: str | None = None,
		source: str | None = None,
		**kwargs: Any,
	) -> None:
		if browser and browser_session:
			raise ValueError('Cannot specify both "browser" and "browser_session".')
		if tools is not None and controller is not None:
			raise ValueError('Cannot specify both "tools" and "controller".')
		self.id = task_id or uuid7str()
		self.task_id = self.id
		self.task = _task_with_schema(_task_with_initial_navigation(task, initial_actions), output_model_schema)
		self.llm = llm
		self.browser_profile = browser_profile
		self.browser_session = browser or browser_session
		self.tools = controller or tools
		self.sensitive_data = sensitive_data
		self.register_done_callback = register_done_callback
		self.register_external_agent_status_raise_error_callback = register_external_agent_status_raise_error_callback
		self.register_should_stop_callback = register_should_stop_callback
		self.output_model_schema = output_model_schema
		self.source = source
		self.kwargs = kwargs
		self.model = _model_name(llm)
		self.state = injected_agent_state or AgentState(agent_id=self.id)
		self.session_id: str | None = None
		self.history: AgentHistoryList[AgentStructuredOutput] = AgentHistoryList(history=[], usage=None)
		self.result: AgentHistoryList[AgentStructuredOutput] | None = None
		self.last_events: list[dict[str, Any]] = []
		self.last_stdout = ''
		self.last_stderr = ''
		self._external_pause_event = asyncio.Event()
		self._external_pause_event.set()

	async def run(
		self,
		max_steps: int = 100,
		on_step_start: AgentHookFunc | None = None,
		on_step_end: AgentHookFunc | None = None,
	) -> AgentHistoryList[AgentStructuredOutput]:
		await self._call_callback(on_step_start, self)
		started = time.time()
		if await self._should_stop_before_run():
			finished = time.time()
			self.result = _history_from_events(
				[],
				model=self.model,
				started=started,
				finished=finished,
				output_model_schema=self.output_model_schema,
				process_error='Rust agent stopped before terminal run.',
			)
			self.history = self.result
			await self._call_callback(on_step_end, self)
			return self.history
		if self.state.paused:
			finished = time.time()
			self.result = _history_from_events(
				[],
				model=self.model,
				started=started,
				finished=finished,
				output_model_schema=self.output_model_schema,
				process_error='Rust agent is paused before terminal run.',
			)
			self.history = self.result
			await self._call_callback(on_step_end, self)
			return self.history
		if self.state.follow_up_task and self.session_id:
			self.state.follow_up_task = False
			return await self.follow_up(self.task, max_steps=max_steps)

		returncode, stdout_text, stderr_text = await self._run_process(self._run_argv(max_steps))
		finished = time.time()
		self.last_stdout = stdout_text
		self.last_stderr = stderr_text
		self.session_id = self._session_id_from_stdout(stdout_text)
		events = await self._load_events()
		process_error = None
		if returncode:
			process_error = stderr_text.strip() or f'browser-use-terminal exited with code {returncode}'
		elif not self.session_id:
			process_error = 'browser-use-terminal did not print a session id.'
		self.last_events = events
		self.result = _history_from_events(
			events,
			model=self.model,
			started=started,
			finished=finished,
			output_model_schema=self.output_model_schema,
			process_error=process_error,
		)
		self.history = self.result
		await self._call_callback(on_step_end, self)
		await self._call_done_callback()
		return self.history

	async def follow_up(self, task: str, max_steps: int | None = None) -> AgentHistoryList[AgentStructuredOutput]:
		if not self.session_id:
			raise RustAgentError('No active Rust session. Call run() before follow_up().')
		started = time.time()
		binary = find_browser_use_terminal_binary()
		returncode, stdout_text, stderr_text = await self._run_process(
			[binary, *self._state_dir_args(), 'followup', self.session_id, task]
		)
		if returncode:
			raise RustAgentError(stderr_text or stdout_text)
		returncode, _stdout_text, stderr_text = await self._run_process(
			self._run_existing_argv(max_steps if max_steps is not None else self.kwargs.get('max_steps', 100))
		)
		finished = time.time()
		process_error = None
		if returncode:
			process_error = stderr_text.strip() or f'browser-use-terminal exited with code {returncode}'
		self.last_events = await self._load_events()
		self.result = _history_from_events(
			self.last_events,
			model=self.model,
			started=started,
			finished=finished,
			output_model_schema=self.output_model_schema,
			process_error=process_error,
		)
		self.history = self.result
		await self._call_done_callback()
		return self.history

	follow_up_task = follow_up

	@property
	def usage(self) -> UsageSummary | None:
		return self.history.usage

	def add_new_task(self, new_task: str) -> None:
		"""Add a follow-up task while keeping the same Browser Use-style agent object."""
		self.task = _task_with_schema(new_task, self.output_model_schema)
		self.state.follow_up_task = True
		self.state.stopped = False
		self.state.paused = False
		self._external_pause_event.set()

	def save_history(self, file_path: str | Path | None = None) -> None:
		"""Save the current Browser Use history to disk."""
		if not file_path:
			file_path = 'AgentHistory.json'
		self.history.save_to_file(file_path, sensitive_data=self.sensitive_data)

	def pause(self) -> None:
		"""Pause the Rust-backed agent before the next terminal run."""
		self.state.paused = True
		self._external_pause_event.clear()

	def resume(self) -> None:
		"""Resume a paused Rust-backed agent."""
		self.state.paused = False
		self._external_pause_event.set()

	def stop(self) -> None:
		"""Stop the Rust-backed agent before the next terminal run."""
		self.state.stopped = True
		self._external_pause_event.set()

	async def close(self) -> None:
		"""Browser Use-compatible close hook.

		The Rust terminal owns browser lifecycle for managed modes, and remote CDP
		browsers are owned by the caller, so the Python wrapper has nothing to close.
		"""
		return None

	def run_sync(
		self,
		max_steps: int = 100,
		on_step_start: AgentHookFunc | None = None,
		on_step_end: AgentHookFunc | None = None,
	) -> AgentHistoryList[AgentStructuredOutput]:
		"""Synchronous wrapper around the async run method."""
		return asyncio.run(self.run(max_steps=max_steps, on_step_start=on_step_start, on_step_end=on_step_end))

	def _run_argv(self, max_steps: int) -> list[str]:
		binary = find_browser_use_terminal_binary()
		return [
			binary,
			*self._state_dir_args(),
			'-c',
			f'max_turns={int(max_steps)}',
			'-c',
			f'browser_mode="{self._browser_mode()}"',
			'run-codex',
			self.task,
			'--model',
			self.model,
		]

	async def _run_process(self, argv: list[str]) -> tuple[int, str, str]:
		proc = await asyncio.create_subprocess_exec(
			*argv,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE,
			env=self._run_env(),
		)
		stdout, stderr = await proc.communicate()
		return proc.returncode or 0, stdout.decode(errors='replace'), stderr.decode(errors='replace')

	async def _call_callback(self, callback: AgentHookFunc | None, *args: Any) -> None:
		if callback is None:
			return
		result = callback(*args)
		if inspect.isawaitable(result):
			await result

	async def _call_done_callback(self) -> None:
		if self.register_done_callback is None or not self.history.is_done():
			return
		result = self.register_done_callback(self.history)
		if inspect.isawaitable(result):
			await result

	async def _should_stop_before_run(self) -> bool:
		if self.state.stopped:
			return True
		if self.register_should_stop_callback is not None:
			should_stop = self.register_should_stop_callback()
			if inspect.isawaitable(should_stop):
				should_stop = await should_stop
			if should_stop:
				self.state.stopped = True
				return True
		if self.register_external_agent_status_raise_error_callback is not None:
			should_stop = self.register_external_agent_status_raise_error_callback()
			if inspect.isawaitable(should_stop):
				should_stop = await should_stop
			if should_stop:
				self.state.stopped = True
				return True
		return False

	def _run_existing_argv(self, max_steps: int) -> list[str]:
		if not self.session_id:
			raise RustAgentError('No active Rust session. Call run() before rerunning an existing session.')
		binary = find_browser_use_terminal_binary()
		return [
			binary,
			*self._state_dir_args(),
			'-c',
			f'max_turns={int(max_steps)}',
			'-c',
			f'browser_mode="{self._browser_mode()}"',
			'run-codex-session',
			self.session_id,
			'--model',
			self.model,
		]

	def _state_dir_args(self) -> list[str]:
		state_dir = os.environ.get('BROWSER_USE_RUST_STATE_DIR')
		return ['--state-dir', state_dir] if state_dir else []

	def _browser_mode(self) -> str:
		if _extract_cdp_url(self.browser_session):
			return 'remote-cdp'
		value = os.environ.get('BROWSER_USE_RUST_BROWSER_MODE')
		if value:
			return value
		if self.browser_profile and getattr(self.browser_profile, 'cdp_url', None):
			return 'managed-headless'
		return os.environ.get('BROWSER_USE_BROWSER_MODE', 'managed-headless')

	def _run_env(self) -> dict[str, str]:
		env = os.environ.copy()
		env['LLM_BROWSER_BROWSER_MODE'] = self._browser_mode()
		cdp_url = _extract_cdp_url(self.browser_session)
		if cdp_url:
			env['BU_CDP_URL'] = cdp_url
		return env

	def _session_id_from_stdout(self, stdout: str) -> str | None:
		for line in reversed(stdout.splitlines()):
			token = line.strip().split()[-1:] or ['']
			candidate = token[0]
			if len(candidate) >= 8 and all(ch in '0123456789abcdef-' for ch in candidate.lower()):
				return candidate
		return None

	async def _load_events(self) -> list[dict[str, Any]]:
		if not self.session_id:
			return []
		binary = find_browser_use_terminal_binary()
		proc = await asyncio.create_subprocess_exec(
			binary,
			*self._state_dir_args(),
			'events',
			self.session_id,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE,
			env=self._run_env(),
		)
		stdout, _stderr = await proc.communicate()
		events = []
		for line in stdout.decode(errors='replace').splitlines():
			try:
				parsed = json.loads(line)
			except json.JSONDecodeError:
				continue
			if isinstance(parsed, dict):
				events.append(parsed)
		return events
