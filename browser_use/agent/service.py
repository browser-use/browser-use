"""Agent(task, llm, browser).run() -> result.final_result(). The browser-use 0.x API on the Pydantic AI REPL engine."""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from pydantic_ai.messages import ModelMessage

from browser_use.agent.loop import Session, build_agent, reasoning_supported, run
from browser_use.agent.prompt import CLOUD_PROMPT
from browser_use.agent.views import AgentHistoryList
from browser_use.browser import Browser
from browser_use.config import load_env
from browser_use.llm import as_chat_model, resolve_model
from browser_use.repl import Repl, check_mode, redact
from browser_use.repl.session import scoped_secrets
from browser_use.tools import Tools

logger = logging.getLogger(__name__)
load_env()  # 0.x read .env on import; credentials below resolve from it

# Hosts a cloud browser cannot reach: localhost, loopback, RFC1918, link-local mDNS (.local).
LOCAL_TARGET = re.compile(
	r'\blocalhost\b|\b127(?:\.\d{1,3}){3}\b|\b0\.0\.0\.0\b|\b10(?:\.\d{1,3}){3}\b|\b192\.168(?:\.\d{1,3}){2}\b'
	r'|\b172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}\b|\[::1\]|(?<![\w:])::1(?![\w:])|\b[a-z0-9-]+\.local\b',
	re.I,
)
UNSUPPORTED = {  # 0.x Agent kwargs -> what to do in 1.0. Anything else unknown raises too.
	'use_vision': 'remove it: the agent takes screenshots when it needs them.',
	'max_actions_per_step': 'remove it: each step is one Python cell.',
	'flash_mode': "remove it, or try mode='ultrafast'.",
	'use_thinking': "use reasoning='low'|'medium'|'high'.",
	'override_system_message': 'use extend_system_message=... (the core prompt is fixed).',
	'browser_profile': 'BrowserProfile was removed; pass Browser(...).',
	'page_extraction_llm': 'remove it: the agent extracts with Python.',
	'file_system_path': 'use workspace=...',
	'available_file_paths': 'put the files in the workspace (workspace=...).',
	'initial_actions': 'describe the first steps in the task instead.',
	'register_new_step_callback': 'not supported yet; read result.messages after the run.',
	'register_done_callback': 'not supported yet; use the value run() returns.',
	'generate_gif': 'not supported in 1.0.',
	'save_conversation_path': 'not supported yet; result.messages holds the transcript.',
	'max_failures': 'remove it: failed cells are retried by the model within max_steps.',
	'fallback_llm': 'not supported yet.',
	'llm_timeout': 'use agent.run(timeout=...) for the agent loop.',
	'step_timeout': 'use agent.run(timeout=...) for the agent loop.',
	'calculate_cost': 'remove it: result.cost_usd is always computed when the price is known.',
	'use_judge': 'not supported in 1.0.',
	'judge_llm': 'not supported in 1.0.',
	'directly_open_url': 'remove it: the agent opens URLs from the task itself.',
}


def _unsupported(kwargs: dict[str, Any], where: str) -> TypeError:
	name = next(iter(kwargs))
	hint = UNSUPPORTED.get(name, 'see MIGRATING.md for the 1.0 options.')
	return TypeError(f'{where}({name}=...) is not supported in browser-use 1.0: {hint}')


class Agent:
	"""agent = Agent('task'); result = await agent.run(); result.final_result()

	llm: default ChatBrowserUse('bu-auto'). browser: default Browser() = a Browser Use Cloud browser; Browser(local=True)
	for your Chrome. sensitive_data={'name': 'value'} (or {'https://site': {'name': 'value'}} to type it only on that
	domain): the model types values with type_secret('name'); secret values are hidden from plain text output. Not a
	sandbox: screenshots and page JS can reveal a typed value. mode='ultrafast' adds accessibility-tree helpers for
	interaction-heavy tasks. reasoning: 'low'|'medium'|'high' (default 'medium') for OpenAI reasoning models, Anthropic
	and Google; OpenAI-compatible chat backends (the gateway, base_url servers) ignore it with a warning: pass
	ChatOpenAI(..., reasoning_effort=...) to send reasoning_effort there."""

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
		self._model_name = self._model_ref = self._provider = ''
		self._repl: Repl | None = None
		self._history: list[ModelMessage] | None = None
		self._continue = False
		self._runner: asyncio.Runner | None = None  # run_sync's event loop, kept while the REPL lives
		self._running = False

	def add_new_task(self, task: str) -> None:
		"""The next run() continues this conversation with a new task."""
		self.task, self._continue = task, True

	def _check_task(self) -> None:
		if self.browser.use_cloud and (m := LOCAL_TARGET.search(self.task)):
			raise ValueError(
				f'The task mentions {m.group()!r}, which a cloud browser cannot reach. '
				'Use a local browser: Agent(task, browser=Browser(local=True)).'
			)

	def _build(self) -> None:
		model, settings = resolve_model(self.llm)  # raises here, before any browser: missing key or extra
		self._model_name = getattr(model, 'model_name', str(model))
		system = getattr(model, 'system', None)  # 'anthropic', 'google-gla', ...: prices are looked up per provider
		self._model_ref = f'{system}:{self._model_name}' if system and ':' not in self._model_name else self._model_name
		self._provider = getattr(self.llm, 'provider', None) or getattr(model, 'system', '')
		if self.reasoning is not None and not reasoning_supported(model):
			logger.warning(
				f'reasoning={self.reasoning!r} is ignored: {self._model_name} gets no reasoning setting. For an '
				'OpenAI-compatible server pass ChatOpenAI(..., reasoning_effort=...) instead.'
			)
		self._agent = build_agent(
			model,
			output_type=self.output_model_schema,
			reasoning_effort=self.reasoning or 'medium',
			instructions='\n'.join(
				filter(
					None,
					[CLOUD_PROMPT if self.browser.use_cloud else '', redact(self.extend_system_message, self.sensitive_data)],
				)
			),
			mode=self.mode,
			tools=self.tools.functions if self.tools else (),
			model_settings=settings,
		)

	async def run(self, max_steps: int = 100, timeout: float = 1700, **kwargs: Any) -> AgentHistoryList:
		"""Run the current task. max_steps: model requests. timeout: seconds for the agent loop (model requests and
		cells); starting the browser before it and stopping it (with cloud downloads) after it are not counted."""
		if kwargs:
			raise _unsupported(kwargs, 'Agent.run')
		if self._running:  # two runs would each start a REPL (one leaks) and stop each other's browser
			raise RuntimeError('This Agent is already running; await that run() first, or use one Agent per concurrent task.')
		self._running = True
		try:
			return await self._run(max_steps, timeout)
		finally:
			self._running = False

	async def _run(self, max_steps: int, timeout: float) -> AgentHistoryList:
		self._check_task()
		if self._agent is None:
			self._build()
		started, result, error = time.monotonic(), None, None
		try:
			if self._repl is None:
				self.workspace.mkdir(parents=True, exist_ok=True)
				env = await self.browser.start()
				self._repl = Repl(self.workspace, env, mode=self.mode, secrets=self.sensitive_data)
			session = Session(repl=self._repl, timeout_s=timeout, max_steps=max_steps)
			history, self._continue = (self._history if self._continue else None), False
			result = await run(
				self._agent,
				self.task,
				session,
				self._model_ref,
				message_history=history,
				explain_error=getattr(self.llm, 'explain_error', None),
			)
			self._history = result.messages
			if result.status == 'error':
				logger.error(result.error)
			return result
		except BaseException as e:
			error = f'{type(e).__name__}: {e}'
			raise
		finally:
			if not self.browser.keep_alive:
				await self._shutdown()
			self._capture(result, error, max_steps, time.monotonic() - started)

	def run_sync(self, max_steps: int = 100, timeout: float = 1700) -> AgentHistoryList:
		"""run() without async. One event loop serves every run_sync() while the REPL lives (Browser(keep_alive=True)),
		because the REPL worker's pipes belong to the loop that started it; close_sync() ends it."""
		self._runner = self._runner or asyncio.Runner()
		try:
			return self._runner.run(self.run(max_steps=max_steps, timeout=timeout))
		finally:
			if self._repl is None:
				self._runner.close()
				self._runner = None

	async def _shutdown(self) -> None:
		"""Stop the REPL and the browser; a cloud browser's downloads land in workspace/downloads."""
		if self._repl:
			await self._repl.close()
			self._repl = None
		await self.browser.stop(downloads_dir=self.workspace / 'downloads')

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

	def _capture(self, result: AgentHistoryList | None, error: str | None, max_steps: int, duration: float) -> None:
		"""One agent_event per run (0.x schema). Never sends code, page content, results or secret values."""
		try:
			from browser_use.telemetry import ProductTelemetry
			from browser_use.telemetry.views import AgentTelemetryEvent
			from browser_use.utils import get_browser_use_version, get_install_source

			usage = result.usage if result else {}
			error = redact(error or (result.error if result else None), self.sensitive_data)
			telemetry = ProductTelemetry()
			telemetry.capture(
				AgentTelemetryEvent(
					task=redact(self.task, self.sensitive_data),
					model=self._model_name,
					model_provider=self._provider,
					max_steps=max_steps,
					max_actions_per_step=None,  # type: ignore[arg-type]
					use_vision=None,  # type: ignore[arg-type]
					version=get_browser_use_version(),
					source=get_install_source(),
					cdp_url=self.browser.cdp_host,
					agent_type='pydantic',
					action_errors=[error] if error else [],
					action_history=None,  # type: ignore[arg-type]
					urls_visited=None,  # type: ignore[arg-type]
					steps=result.steps if result else 0,
					total_input_tokens=usage.get('input', 0),
					total_output_tokens=usage.get('output', 0),
					prompt_cached_tokens=usage.get('cache_read', 0),
					total_tokens=usage.get('input', 0) + usage.get('output', 0),
					total_duration_seconds=duration,
					success=result.is_successful() if result else None,
					final_result_response=None,
					error_message=error,
				)
			)
			telemetry.flush()
		except Exception as e:  # - telemetry never breaks a run
			logger.debug('telemetry failed: %s', e)
