"""Agent(task, llm, browser).run() -> result.final_result(). The browser-use 0.x API on the Pydantic AI REPL engine."""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, RetryPromptPart, ToolCallPart

from browser_use.agent.loop import Session, build_agent, reasoning_supported, run
from browser_use.agent.prompt import CAPTCHA_PROMPT, CLOUD_PROMPT, NO_CAPTCHA_PROMPT
from browser_use.agent.views import AgentHistoryList
from browser_use.browser import Browser
from browser_use.browser.browser import json_page_copies
from browser_use.config import load_env
from browser_use.exceptions import removed
from browser_use.llm import ChatBrowserUse, as_chat_model, gateway_llm, resolve_model
from browser_use.repl import Repl, check_mode, redact
from browser_use.repl.session import check_loop, scoped_secrets
from browser_use.tools import Tools

logger = logging.getLogger(__name__)
load_env()  # 0.x read .env on import; credentials below resolve from it

# Hosts a cloud browser cannot reach: localhost, loopback, RFC1918, link-local mDNS (.local).
LOCAL_TARGET = re.compile(
	r'\blocalhost\b|\b127(?:\.\d{1,3}){3}\b|\b0\.0\.0\.0\b|\b10(?:\.\d{1,3}){3}\b|\b192\.168(?:\.\d{1,3}){2}\b'
	r'|\b172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}\b|\[::1\]|(?<![\w:])::1(?![\w:])|\b[a-z0-9-]+\.local\b',
	re.I,
)
REASONING = (None, 'low', 'medium', 'high')
_SCREENSHOTS = 'the agent takes screenshots when it needs them.'
_MESSAGES = 'result.messages holds the whole transcript after the run.'
_CANCEL = 'cancel the task that awaits agent.run(), or pass run(timeout=seconds).'
REMOVED = {  # 0.x Agent(...) and run() arguments -> the 1.0 alternative ('' when there is none). MIGRATING.md lists them.
	'use_vision': _SCREENSHOTS,
	'vision_detail_level': _SCREENSHOTS,
	'llm_screenshot_size': _SCREENSHOTS,
	'sample_images': _SCREENSHOTS,
	'max_actions_per_step': 'each step is one Python cell.',
	'flash_mode': "mode='ultrafast'.",
	'use_thinking': "reasoning='low' | 'medium' | 'high'.",
	'override_system_message': 'extend_system_message=... (the core prompt is fixed).',
	'browser_profile': 'pass options to Browser(...).',
	'page_extraction_llm': 'the agent extracts with Python.',
	'extraction_schema': 'the agent extracts with Python.',
	'file_system_path': 'workspace=...',
	'available_file_paths': 'put the files in the workspace (workspace=...).',
	'initial_actions': 'describe the first steps in the task.',
	'directly_open_url': 'the agent opens URLs from the task itself.',
	'register_new_step_callback': _MESSAGES,
	'register_done_callback': 'use the result agent.run() returns.',
	'register_external_agent_status_raise_error_callback': _CANCEL,
	'register_should_stop_callback': _CANCEL,
	'on_step_start': _MESSAGES,
	'on_step_end': _MESSAGES,
	'save_conversation_path': _MESSAGES,
	'save_conversation_path_encoding': _MESSAGES,
	'max_failures': 'failed cells are retried by the model within max_steps.',
	'final_response_after_failure': 'failed cells are retried by the model within max_steps.',
	'llm_timeout': 'agent.run(timeout=seconds) bounds the agent loop.',
	'step_timeout': 'agent.run(timeout=seconds) bounds the agent loop.',
	'calculate_cost': 'result.cost_usd is computed whenever the price is known.',
	'pricing_url': 'result.cost_usd is computed whenever the price is known.',
	**dict.fromkeys(('generate_gif', 'demo_mode', 'fallback_llm', 'use_judge', 'judge_llm', 'ground_truth'), ''),
	**dict.fromkeys(('skill_ids', 'skills', 'skill_service'), ''),  # Cloud Skills
	**dict.fromkeys(  # the 0.x planner and loop tuning
		(
			'enable_planning',
			'planning_replan_on_stall',
			'planning_exploration_limit',
			'planner_llm',
			'planner_interval',
			'is_planner_reasoning',
			'extend_planner_system_message',
			'use_vision_for_planner',
			'loop_detection_window',
			'loop_detection_enabled',
			'message_compaction',
			'max_history_items',
			'include_attributes',
			'max_clickable_elements_length',
			'include_recent_events',
			'include_tool_call_examples',
			'display_files_in_done_text',
			'injected_agent_state',
			'source',
			'task_id',
			'enable_signal_handler',
			'_url_shortening_limit',
		),
		'',
	),
}
REMOVED_METHODS = {  # 0.x Agent methods -> the 1.0 alternative
	'pause': _CANCEL,
	'resume': '',
	'stop': _CANCEL,
	'step': 'agent.run(max_steps=...) runs the loop.',
	'take_step': 'agent.run(max_steps=...) runs the loop.',
	'multi_act': 'the model acts in Python cells.',
	'save_history': _MESSAGES,
	'load_and_rerun': 'run the task again.',
	'rerun_history': 'run the task again.',
	'detect_variables': '',
}


def _unsupported(kwargs: dict[str, Any], where: str) -> TypeError:
	name = next(iter(kwargs))
	if name in REMOVED:
		return TypeError(removed(f'{where}({name}=...)', REMOVED[name]))
	return TypeError(
		f'{where}({name}=...) is not a browser-use 1.0 option; MIGRATING.md lists the options and what replaced 0.x ones.'
	)


class Agent:
	"""agent = Agent('task'); result = await agent.run(); result.final_result()

	llm: default ChatBrowserUse('bu-fast'). browser: default Browser() = a Browser Use Cloud browser; Browser('chromium')
	for a fresh local one, Browser('chrome') for the Chrome you have open. sensitive_data={'name': 'value'} (or {'https://site': {'name': 'value'}} to type it only on that
	domain): the model types values with type_secret('name'); values become <secret:name> in cell output, checkpoints,
	tool results, the task and the result (MIGRATING.md "Trust model" lists exactly where). Not a sandbox: model-written
	Python can read them; screenshots, page JS and a cloud live view or recording can reveal a typed value. mode='ultrafast' adds accessibility-tree helpers for
	interaction-heavy tasks. reasoning: 'low'|'medium'|'high' for OpenAI reasoning models, the gateway, Anthropic and
	Google (default 'medium'; on the gateway the alias's own: bu-fast medium, bu-ultrafast low, bu-smart high).
	OpenAI-compatible chat backends (base_url servers) ignore it with a warning: pass ChatOpenAI(..., reasoning_effort=...)
	to send reasoning_effort there."""

	def __init__(
		self,
		task: str,
		llm: Any = None,
		*,
		browser: Browser | None = None,
		browser_session: Browser | None = None,
		tools: Tools | None = None,
		controller: Tools | None = None,
		output_model_schema: Any = None,
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		extend_system_message: str | None = None,
		reasoning: str | None = None,
		mode: str | None = 'default',
		workspace: str | Path | None = None,
		**kwargs: Any,
	):
		if kwargs:
			raise _unsupported(kwargs, 'Agent')
		if reasoning not in REASONING:  # a typo would start (and bill) a browser, then 400 on the first model request
			raise ValueError(f"reasoning must be 'low', 'medium', 'high' or None, not {reasoning!r}")
		if browser and browser_session:
			raise ValueError('Pass browser=... or browser_session=..., not both')
		browser = browser or browser_session or Browser()
		if not isinstance(browser, Browser):
			raise TypeError(f'browser must be browser_use.Browser, not {type(browser).__name__}. See MIGRATING.md.')
		tools = tools or controller
		if tools is not None and not isinstance(tools, Tools):
			raise TypeError(f'tools must be browser_use.Tools, not {type(tools).__name__}')
		scoped_secrets(sensitive_data)  # raises on a non-string value
		self.mode = check_mode(mode)
		self.task, self.llm, self.browser, self.tools = task, as_chat_model(llm), browser, tools
		self.output_model_schema = output_model_schema or str
		self.sensitive_data = dict(sensitive_data or {})
		self.extend_system_message, self.reasoning = extend_system_message or '', reasoning
		self.workspace = Path(workspace or tempfile.mkdtemp(prefix='browser-use-')).resolve()
		self._agent: Any = None
		self._gateway: ChatBrowserUse | None = None  # set by _build when the model runs on the Browser Use gateway
		self._preflighted = False
		self._model_name = self._model_ref = self._provider = ''
		self._repl: Repl | None = None
		self._history: list[ModelMessage] | None = None
		self._continue = False
		self._runner: asyncio.Runner | None = None  # run_sync's event loop, kept while the REPL lives
		self._running = False
		self._custom_workspace = workspace is not None
		self._downloads: list[Path] = []  # what the last stop() copied from a cloud browser (telemetry counts them)

	def __getattr__(self, name: str) -> Any:
		if name in REMOVED_METHODS:
			raise AttributeError(removed(f'Agent.{name}()', REMOVED_METHODS[name]))
		raise AttributeError(f'{type(self).__name__!r} object has no attribute {name!r}')

	def add_new_task(self, task: str) -> None:
		"""The next run() continues this conversation with a new task."""
		self.task, self._continue = task, True

	def _check_task(self) -> None:
		if self.browser.use_cloud and (m := LOCAL_TARGET.search(self.task)):  # a hint, never a refusal
			logger.warning(
				f'The task mentions {m.group()!r}; a cloud browser cannot reach your localhost or private network. '
				"If that is the target, use a local browser: Agent(task, browser=Browser('chromium'))."
			)

	def _build(self) -> None:
		model, settings = resolve_model(self.llm)  # raises here, before any browser: missing key or extra
		self._model_name = getattr(model, 'model_name', str(model))
		system = getattr(model, 'system', None)  # 'anthropic', 'google-gla', ...: prices are looked up per provider
		self._model_ref = f'{system}:{self._model_name}' if system and ':' not in self._model_name else self._model_name
		self._gateway = gateway_llm(model)  # any form: ChatBrowserUse, ChatOpenAI(base_url=gateway), pydantic_model()
		if self._gateway:  # cost is only what the gateway charged (charge_usd), never a retail estimate
			self._model_ref = f'browser-use:{self._model_name}'
		self._provider = getattr(self.llm, 'provider', None) or getattr(model, 'system', '')
		if self.reasoning is not None and not reasoning_supported(model):
			logger.warning(
				f'reasoning={self.reasoning!r} is ignored: {self._model_name} gets no reasoning setting. For an '
				'OpenAI-compatible server pass ChatOpenAI(..., reasoning_effort=...) instead.'
			)
		self._agent = build_agent(
			model,
			output_type=self.output_model_schema,
			reasoning_effort=self.reasoning or (None if self._gateway else 'medium'),
			instructions='\n'.join(
				filter(
					None,
					[
						f'{CLOUD_PROMPT} {CAPTCHA_PROMPT if self.browser.captcha_solver else NO_CAPTCHA_PROMPT}'
						if self.browser.use_cloud
						else '',
						self.browser.domains.prompt(
							browser_blocks=not self.browser._attached()
						),  # '' without restrictions: the default prompt stays byte-identical
						redact(self.extend_system_message, self.sensitive_data),
					],
				)
			),
			mode=self.mode,
			tools=self.tools.functions if self.tools else (),
			model_settings=settings,
		)

	async def run(self, max_steps: int = 100, timeout: float = 1700, **kwargs: Any) -> AgentHistoryList:
		"""Run the current task. max_steps: model requests; request max_steps-1 is a delivery-only turn and the last
		one is kept for a delivery repair. timeout: seconds for the agent loop (model requests and cells); starting the
		browser before it and stopping it (with cloud downloads) after it are not counted."""
		if kwargs:
			raise _unsupported(kwargs, 'Agent.run')
		if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
			raise ValueError(f'max_steps must be a whole number >= 1, not {max_steps!r}')
		if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not timeout > 0:
			raise ValueError(f'timeout must be a number of seconds > 0, not {timeout!r}')
		if self._running:  # two runs would each start a REPL (one leaks) and stop each other's browser
			raise RuntimeError('This Agent is already running; await that run() first, or use one Agent per concurrent task.')
		if self.browser._user is not None:  # two Agents on one browser drive one tab, and the first to end stops it
			raise RuntimeError(
				'This Browser is in use by another running Agent. Give each concurrent Agent its own Browser(); '
				'one Browser(keep_alive=True) can serve several Agents one after another.'
			)
		self._running, self.browser._user = True, self
		try:
			return await self._run(max_steps, timeout)
		finally:
			self._running, self.browser._user = False, None

	async def _run(self, max_steps: int, timeout: float) -> AgentHistoryList:
		self._check_task()
		if self._agent is None:
			self._build()
		started, result, error_type, session, browser_s = time.monotonic(), None, None, None, None
		follow_up = self._continue
		prior = len(self._history or []) if follow_up else 0  # messages of earlier tasks, not counted for this run
		self._downloads = []
		try:
			if self._repl is None:
				check_loop()  # before the browser starts: a cloud browser bills from its create
				if self._gateway and not self._preflighted:  # a dead gateway or a bad model fails before any browser
					if error := await asyncio.to_thread(self._gateway.preflight):
						logger.error(error)
						usage = {'input': 0, 'output': 0, 'cache_read': 0, 'cache_write': 0, 'requests': 0}
						duration = time.monotonic() - started
						result = AgentHistoryList('error', '', None, 0, duration, usage, 0.0, None, error, [], None)
						return result
					self._preflighted = True
				self.workspace.mkdir(parents=True, exist_ok=True)
			self.browser._downloads_dir = self.workspace / 'downloads'  # a keep_alive browser's later stop() copies there
			env = await self.browser.start()  # also on a follow-up: a daemon that died since is started again
			if self._repl is None or env != self._repl.env:  # or the browser was stopped and started again since
				if self._repl is None:
					browser_s = time.monotonic() - started
				else:
					await self._repl.close()
				self._repl = Repl(
					self.workspace,
					env,
					mode=self.mode,
					secrets=self.sensitive_data,
					reattach=self.browser.reattach,
					after_cell=self.browser.after_cell if self.browser.domains else None,
				)
			session = Session(repl=self._repl, timeout_s=timeout, max_steps=max_steps)
			history, self._continue = (self._history if self._continue else None), False
			result = await run(
				self._agent,
				self.task,
				session,
				self._model_ref,
				message_history=history,
				explain_error=self._gateway.explain_error if self._gateway else None,
			)
			self._history = result.messages
			if result.status == 'error':
				logger.error(result.error)
			return result
		except BaseException as e:
			error_type = type(e).__name__
			raise
		finally:
			self.browser.json_page_copies |= json_page_copies(self.workspace / '.browser-use' / 'downloads.jsonl')
			if not self.browser.keep_alive:
				await self._shutdown()
			self._capture(result, session, error_type, max_steps, timeout, prior, browser_s, time.monotonic() - started)

	def run_sync(self, max_steps: int = 100, timeout: float = 1700, **kwargs: Any) -> AgentHistoryList:
		"""run() without async. One event loop serves every run_sync() while the REPL lives (Browser(keep_alive=True)),
		because the REPL worker's pipes belong to the loop that started it; close_sync() ends it."""
		if kwargs:
			raise _unsupported(kwargs, 'Agent.run_sync')
		self._runner = self._runner or asyncio.Runner()
		try:
			return self._runner.run(self.run(max_steps=max_steps, timeout=timeout))
		finally:
			if self._repl is None:
				self._runner.close()
				self._runner = None

	async def _shutdown(self) -> None:
		"""Stop the REPL and the browser; a cloud browser's downloads land in workspace/downloads. The browser stops
		even when the REPL's close fails or is cancelled (a cloud browser bills until then); the cancel still raises."""
		try:
			if self._repl:
				repl, self._repl = self._repl, None
				await repl.close()
		finally:
			self._downloads = await self.browser.stop(downloads_dir=self.workspace / 'downloads') or []

	async def close(self) -> None:
		"""Stop the REPL, and the browser unless Browser(keep_alive=True). Also closes run_sync()'s event loop when
		called from another one (inside it, use close_sync())."""
		try:
			if self.browser.keep_alive:
				if self._repl:
					await self._repl.close()
					self._repl = None
				return
			await self._shutdown()
		finally:
			runner = self._runner
			if runner is not None and runner.get_loop() is not asyncio.get_running_loop():
				self._runner = None
				runner.get_loop().close()  # idle: its REPL is gone; Runner.close() cannot run inside another loop

	def close_sync(self) -> None:
		"""close() without async, on run_sync()'s event loop (the REPL worker belongs to it), then closes that loop."""
		runner, self._runner = self._runner, None
		if runner is None:
			asyncio.run(self.close())
			return
		try:
			runner.run(self.close())
		finally:
			runner.close()

	async def __aenter__(self) -> Agent:
		return self

	async def __aexit__(self, *exc: object) -> None:
		await self.close()

	def _capture(
		self,
		result: AgentHistoryList | None,
		session: Session | None,
		error_type: str | None,
		max_steps: int,
		timeout: float,
		prior: int,
		browser_s: float | None,
		duration: float,
	) -> None:
		"""One agent_event per run. Counts, names, hostnames and classes only: never the task, the result, code, typed
		text, secrets, page content, URLs or error messages (TELEMETRY.md)."""
		try:
			from collections import Counter

			from browser_use.telemetry import ProductTelemetry
			from browser_use.telemetry.stats import RunStats, cdp_category, host, top
			from browser_use.telemetry.views import AgentTelemetryEvent
			from browser_use.utils import get_browser_use_version, get_install_source

			stats = session.stats if session else RunStats()
			status = (
				result.status if result else 'cancelled' if error_type in ('CancelledError', 'KeyboardInterrupt') else 'error'
			)
			usage = result.usage if result else {}
			messages = result.messages[prior:] if result else []
			tools = Counter(
				p.tool_name for m in messages if isinstance(m, ModelResponse) for p in m.parts if isinstance(p, ToolCallPart)
			)
			retries = sum(isinstance(p, RetryPromptPart) for m in messages if isinstance(m, ModelRequest) for p in m.parts)
			schema = self.output_model_schema
			fields = getattr(schema, 'model_fields', None)
			secrets = scoped_secrets(self.sensitive_data)
			browser = self.browser
			mode = browser.kind  # cloud | chromium | chrome | cdp
			downloads = self._downloads
			telemetry = ProductTelemetry()
			telemetry.capture(
				AgentTelemetryEvent(
					version=get_browser_use_version(),
					source=get_install_source(),
					run_id=uuid.uuid4().hex,
					model=self._model_name,
					model_provider=self._provider,
					reasoning=self.reasoning,
					mode=self.mode,
					max_steps=max_steps,
					timeout_s=timeout,
					structured_output=schema is not str,
					output_schema_fields=len(fields) if isinstance(fields, dict) else None,
					custom_tools=sorted(t.name for t in self.tools.functions)[:50] if self.tools else [],
					sensitive_data_count=len({n for n, _, _ in secrets}),
					sensitive_data_domain_scoped=sum(d is not None for _, _, d in secrets),
					extend_system_message=bool(self.extend_system_message),
					custom_workspace=self._custom_workspace,
					follow_up=prior > 0,
					task_chars=len(self.task),
					browser_mode=mode,
					cdp_url=cdp_category(host(browser.cdp_url)) if mode == 'cdp' else None,
					keep_alive=browser.keep_alive,
					cloud_profile=bool(browser.use_cloud and browser.profile),
					cloud_proxy_country=browser.proxy if browser.use_cloud else None,
					cloud_timeout_min=browser.timeout if browser.use_cloud else None,
					live_view=bool(browser.live_view),
					browser_start_seconds=browser_s,
					status=status,
					success=result.is_successful() if result else None,
					max_steps_hit=status == 'max_steps' or bool(session and session.budget_hit == 'max_steps'),
					timed_out=status == 'timeout',
					finish_via=session.finish_via if session and status == 'completed' else None,
					partial_used=bool(result and status != 'completed' and result.partial is not None),
					error_type=error_type or (session.error_type if session and status == 'error' else None),
					output_chars=len(result.text) if result else 0,
					total_duration_seconds=duration,
					steps=result.steps if result else 0,
					model_requests=usage.get('requests', 0),
					total_input_tokens=usage.get('input', 0),
					total_output_tokens=usage.get('output', 0),
					prompt_cached_tokens=usage.get('cache_read', 0),
					cache_write_tokens=usage.get('cache_write', 0),
					total_tokens=usage.get('input', 0) + usage.get('output', 0),
					cost_usd=result.cost_usd if result else None,
					tool_calls=top(tools),
					retry_prompts=retries,
					cells=stats.cells,
					cell_errors=stats.cell_errors,
					cell_seconds=round(stats.cell_seconds, 3),
					cell_error_types=top(stats.error_types),
					helper_counts=top(stats.helpers),
					cdp_method_counts=top(stats.cdp_methods),
					imports=top(stats.imports),
					screenshots=stats.images,
					domains=list(top(stats.domains)),
					domain_count=len(stats.domains),
					navigations=stats.navigations,
					captcha_started=stats.events['captcha_started'],
					captcha_solved=stats.events['captcha_solved'],
					captcha_failed=stats.events['captcha_failed'],
					downloads_started=stats.events['download_started'],
					domain_restrictions=bool(browser.domains),
					domain_blocks=stats.events['domain_blocked'],
					downloads=len(downloads),
					download_exts=top(Counter(p.suffix.lower().lstrip('.')[:10] or 'none' for p in downloads)),
				)
			)
			telemetry.flush()
		except Exception as e:  # - telemetry never breaks a run
			logger.debug('telemetry failed: %s', e)
