"""Agent(task, llm, browser).run() -> result.final_result(). The browser-use 0.x API on the Pydantic AI REPL engine."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from genai_prices import calc_price
from pydantic import TypeAdapter
from pydantic_ai.messages import (
	BinaryContent,
	ModelMessage,
	ModelRequest,
	ModelResponse,
	RetryPromptPart,
	ToolCallPart,
	ToolReturnPart,
)
from pydantic_ai.usage import RequestUsage

from browser_use.agent.judge import FINAL_SCREENSHOT_TIMEOUT_S, judge_run
from browser_use.agent.loop import Session, build_agent, model_kind, reasoning_supported, run, usage_and_cost
from browser_use.agent.prompt import CAPTCHA_PROMPT, CLOUD_PROMPT, LOCAL_PROMPT, NO_CAPTCHA_PROMPT, SEARCH_PROMPT
from browser_use.agent.views import AgentHistoryList
from browser_use.auth import browser_use_api_key
from browser_use.browser import Browser
from browser_use.browser import browser as browser_module
from browser_use.config import load_env
from browser_use.exceptions import BrowserConfigError, MissingAPIKeyError, removed
from browser_use.llm import (
	GATEWAY_URL,
	ChatBrowserUse,
	as_chat_model,
	gateway_alias,
	gateway_llm,
	provider_preflight,
	resolve_model,
)
from browser_use.repl import Repl, check_mode, redact
from browser_use.repl.session import SHORT_SECRET, check_loop, scoped_secrets, secret_forms
from browser_use.search import WebSearch, search_url
from browser_use.telemetry.feedback import RunReports
from browser_use.telemetry.recorder import RunRecorder, now
from browser_use.telemetry.stats import model_id
from browser_use.tools import Tools
from browser_use.utils import raise_fd_limit

logger = logging.getLogger(__name__)
load_env()  # 0.x read .env on import; credentials below resolve from it

# Hosts a cloud browser cannot reach: localhost, loopback, RFC1918, link-local mDNS (.local).
LOCAL_TARGET = re.compile(
	r'\blocalhost\b|\b127(?:\.\d{1,3}){3}\b|\b0\.0\.0\.0\b|\b10(?:\.\d{1,3}){3}\b|\b192\.168(?:\.\d{1,3}){2}\b'
	r'|\b172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}\b|\[::1\]|(?<![\w:])::1(?![\w:])|\b[a-z0-9-]+\.local\b',
	re.I,
)
REASONING = (None, 'low', 'medium', 'high')
_RUNS = itertools.count(1)  # Agent.run() calls in this process (telemetry run_in_process)
_ACTIVE = [0]  # runs in progress in this process (telemetry concurrent_runs)
_SCREENSHOTS = 'the agent takes screenshots when it needs them.'
_MESSAGES = 'result.messages holds the whole transcript after the run.'
_LIVE = (
	"each step logs one INFO line to logging.getLogger('browser_use'): add a logging.Handler to watch a run live. " + _MESSAGES
)
_CANCEL = (
	'task = asyncio.create_task(agent.run()), later task.cancel() (from another thread: '
	'loop.call_soon_threadsafe(task.cancel)). run() then raises CancelledError and the browser stops. '
	'For a partial result instead, bound the run: run(timeout=seconds, max_steps=n).'
)
REMOVED = {  # 0.x Agent(...) and run() arguments -> the 1.0 alternative ('' when there is none). MIGRATING.md lists them.
	'use_vision': _SCREENSHOTS,
	'vision_detail_level': _SCREENSHOTS,
	'llm_screenshot_size': _SCREENSHOTS,
	'sample_images': _SCREENSHOTS,
	'max_actions_per_step': 'each step is one Python cell.',
	'flash_mode': "mode='ultrafast'.",
	'highlight_elements': 'Agent(highlight_actions=True | False) turns the action highlights on or off.',
	'use_thinking': "reasoning='low' | 'medium' | 'high'.",
	'override_system_message': 'extend_system_message=... (the core prompt is fixed).',
	'browser_profile': 'pass options to Browser(...).',
	'page_extraction_llm': 'the agent extracts with Python.',
	'extraction_schema': 'the agent extracts with Python.',
	'file_system_path': 'workspace=...',
	'available_file_paths': 'there is no file allowlist: the agent runs Python as your user and can read and upload any file '
	'you can read. Put task files in the workspace (workspace=...); run untrusted tasks in a container or VM.',
	'initial_actions': 'describe the first steps in the task.',
	'directly_open_url': 'the agent opens URLs from the task itself.',
	'register_new_step_callback': _LIVE,
	'register_done_callback': 'use the result agent.run() returns.',
	'register_external_agent_status_raise_error_callback': _CANCEL,
	'register_should_stop_callback': _CANCEL,
	'on_step_start': _LIVE,
	'on_step_end': _LIVE,
	'save_conversation_path': _MESSAGES,
	'save_conversation_path_encoding': _MESSAGES,
	'max_failures': 'failed cells are retried by the model within max_steps.',
	'final_response_after_failure': 'failed cells are retried by the model within max_steps.',
	'llm_timeout': 'agent.run(timeout=seconds) bounds the agent loop.',
	'step_timeout': 'agent.run(timeout=seconds) bounds the agent loop.',
	'calculate_cost': 'result.cost_usd is computed whenever the price is known.',
	'pricing_url': 'result.cost_usd is computed whenever the price is known.',
	**dict.fromkeys(('generate_gif', 'demo_mode', 'fallback_llm'), ''),
	'judge_llm': "the judge uses the agent's own llm.",
	**dict.fromkeys(('skill_ids', 'skills', 'skill_service'), ''),  # Cloud Skills
	# 0.1-0.8 arguments (every tag's Agent.__init__); they raised "not a browser-use 1.0 option" without an answer
	**dict.fromkeys(('browser_context', 'context', 'page'), 'pass a Browser(...) as browser=...'),
	'validate_output': "result.success, the agent's own verdict.",
	'system_prompt_class': 'extend_system_message=... (the core prompt is fixed).',
	'message_context': 'put the context in the task or extend_system_message=...',
	**dict.fromkeys(('enable_memory', 'memory_config', 'memory_interval'), 'long runs compact their history on their own.'),
	'max_input_tokens': 'max_context_chars=... (history is compacted past 75% of it).',
	'images_per_step': 'the agent takes screenshots when it needs them.',
	'retry_delay': 'model requests are retried by Pydantic AI.',
	'save_playwright_script_path': _MESSAGES,
	**dict.fromkeys(
		('cloud_sync', 'preload', 'max_error_length', 'tool_calling_method', 'tool_call_in_content'),
		'',
	),
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
# REMOVED tuning knobs that cannot change what a run returns: warn and run (0.x scripts set them often), the rest raise.
IGNORED = {  # use_vision=False is kept (no screenshots reach the model); use_vision=True / 'auto' is ignored
	'use_vision',
	'vision_detail_level',
	'llm_screenshot_size',
	'max_actions_per_step',
	'flash_mode',
	'highlight_elements',  # 0.x Agent took it in **kwargs and did nothing with it (a BrowserProfile option)
	'use_thinking',
	'max_failures',
	'final_response_after_failure',
	'calculate_cost',
}
REMOVED_ATTRS = {  # 0.x Agent attributes -> the 1.0 alternative
	'state': 'the result agent.run() returns (status, steps, usage, errors()). To stop a run (0.x state.should_stop): ' + _CANCEL,
	'history': 'the result agent.run() returns.',
	'message_manager': 'result.messages holds the whole transcript.',
	'settings': 'the Agent(...) arguments are attributes (agent.task, agent.llm, agent.browser, ...).',
	'browser_session': 'agent.browser.',
	'browser_profile': 'agent.browser.',
	'browser_context': 'agent.browser.',
	'controller': 'agent.tools.',
	'file_system': 'agent.workspace (a directory).',
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
	'set_task': 'agent.add_new_task(task) continues the conversation; Agent(task) starts a new one.',
	'wait_until_resumed': _CANCEL,
	**dict.fromkeys(('get_next_action', 'get_model_output', 'set_tool_calling_method'), 'the model acts in Python cells.'),
	**dict.fromkeys(('create_history_gif', 'get_trace_object', 'authenticate_cloud_sync', 'save_file_system_state'), ''),
	**dict.fromkeys(('log_completion', 'logger'), "logging.getLogger('browser_use')."),
	**dict.fromkeys(('current_llm_model', 'is_using_fallback_llm'), 'agent.llm (there is no fallback model).'),
}


def _check_task_arg(task: Any) -> None:
	"""Before anything starts: None, '' or a number started (and billed) a browser, then failed."""
	if not isinstance(task, str):
		raise TypeError(f'task must be a str, not {type(task).__name__}')
	if not task.strip():
		raise ValueError('task is empty: say what the agent should do')


def _unsupported(kwargs: dict[str, Any], where: str) -> TypeError:
	name = next(iter(kwargs))
	if name == 'max_steps':
		return TypeError(f'{where}(max_steps=...) is not an option: pass it to agent.run(max_steps=...).')
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
	Python can read them; screenshots, page JS and a cloud live view or recording can reveal a typed value. mode='ultrafast'
	adds accessibility-tree helpers; the default (None) is 'ultrafast' on bu-fast and bu-ultrafast, else 'default'
	(mode='default' opts out). reasoning: 'low'|'medium'|'high' for OpenAI reasoning models, the gateway, Anthropic and
	Google (default 'medium'; on the gateway the alias's own: bu-fast medium, bu-ultrafast low, bu-smart high).
	OpenAI-compatible chat backends (base_url servers) ignore it with a warning: pass ChatOpenAI(..., reasoning_effort=...)
	to send reasoning_effort there. web_search: the agent gets search() (Browser Use web search, billed per search to the
	Browser Use key). Off by default; True turns it on (raises without a Browser Use key, or with allowed_domains,
	since search would reach sites the browser may not open). max_context_chars: past 75% of this many characters of
	conversation the agent compacts its history into a summary checkpoint (default 4 per token of the model's context
	window, as Browser Use Pi; not used where the provider compacts server-side, as on OpenAI Responses and the gateway).
	highlight_actions: orange corner brackets show for 1 s around what the agent clicks or types into (as 0.x); never in
	the agent's screenshots. False turns them off. judge: after each run one more request to the same llm judges it
	against the task: result.judgement (success, failure_reason, description, prompt_injection_detected,
	bot_block_or_captcha_detected, gotchas), its tokens and cost counted in result.usage and result.cost_usd; False turns
	it off. judge_context: your criteria or the expected answer, which the judge puts first (0.x ground_truth)."""

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
		mode: str | None = None,
		workspace: str | Path | None = None,
		web_search: bool = False,
		max_context_chars: int | None = None,
		highlight_actions: bool = True,
		judge: bool = True,
		judge_context: str | None = None,
		**kwargs: Any,
	):
		# 0.x use_judge and ground_truth: the same options under their old names
		judge = kwargs.pop('use_judge', judge)
		judge_context = kwargs.pop('ground_truth', judge_context)
		# 0.x use_vision=False: no screenshot reaches the model (privacy, cost, text-only models); kept, not ignored
		self.use_vision = kwargs.get('use_vision') is not False
		for name in [n for n in kwargs if n in IGNORED]:
			hint = REMOVED[name]
			if (name, kwargs.pop(name)) != ('use_vision', False):
				logger.warning(f'Agent({name}=...) is ignored in browser-use 1.0' + (f': {hint}' if hint else '.'))
		if kwargs:
			raise _unsupported(kwargs, 'Agent')
		_check_task_arg(task)
		if not isinstance(web_search, bool):
			raise TypeError(f'web_search must be True or False, not {web_search!r}')
		if not isinstance(highlight_actions, bool):
			raise TypeError(f'highlight_actions must be True or False, not {highlight_actions!r}')
		if not isinstance(judge, bool):
			raise TypeError(f'judge must be True or False, not {judge!r}')
		if judge_context is not None and not isinstance(judge_context, str):
			raise TypeError(f'judge_context must be a str or None, not {type(judge_context).__name__}')
		if max_context_chars is not None and (type(max_context_chars) is not int or max_context_chars < 1):
			raise ValueError(f'max_context_chars must be a positive int or None, not {max_context_chars!r}')
		if llm is None and os.environ.get('DEFAULT_LLM'):  # 0.x read it; 1.0 runs (and bills) bu-fast instead
			logger.warning(
				'DEFAULT_LLM is set but browser-use 1.0 does not read it: this run uses bu-fast. Pass llm=... instead.'
			)
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
		if sensitive_data is not None and not isinstance(sensitive_data, dict):
			raise TypeError(
				"sensitive_data must be a dict: {'name': 'value'} or {'https://site.com': {'name': 'value'}}, "
				f'not {type(sensitive_data).__name__}'
			)
		short = sorted({n for n, v, _ in scoped_secrets(sensitive_data) if 0 < len(v) < SHORT_SECRET})  # raises on non-str
		if short:
			logger.warning(
				f'sensitive_data {", ".join(short)}: values under {SHORT_SECRET} characters are redacted only where they '
				'stand alone, not inside longer words or numbers; a longer value is safer.'
			)
		self.task, self.llm, self.browser, self.tools = task, as_chat_model(llm), browser, tools
		self._tasks = [task]  # every task this agent ran (follow-ups too): telemetry never sends their text
		# bu-fast and bu-ultrafast are evaluated in ultrafast mode (Google Flights: 0/3 in default mode, 3/3)
		fast = gateway_alias(self.llm) in ('bu-fast', 'bu-ultrafast')
		self.mode = check_mode(mode if mode is not None else 'ultrafast' if fast else 'default')
		self.output_model_schema = output_model_schema or str
		try:  # a JSON-schema dict or an instance failed only in run(), with a raw pydantic SchemaError
			TypeAdapter(self.output_model_schema).json_schema()
		except Exception as e:
			raise TypeError(
				'output_model_schema must be a type (a Pydantic model, list[Model], Literal[...]), not '
				f'{output_model_schema!r:.100}. For a JSON-schema dict use pydantic_ai.StructuredDict(schema).'
			) from e
		self.sensitive_data = dict(sensitive_data or {})
		self.extend_system_message, self.reasoning = extend_system_message or '', reasoning
		self.web_search, self.max_context_chars, self.highlight_actions = web_search, max_context_chars, highlight_actions
		self.judge, self.judge_context = judge, judge_context or None
		self._judge_cost: float | None = None  # the last run's judge cost (telemetry)
		self._final_page: BinaryContent | None = None  # the last run's final page, for the judge
		self._search: WebSearch | None = None  # set by _build when search() is on
		# As given, made absolute, symlinks kept: on macOS resolve() turned tempfile's /var/... into /private/var/..., and
		# result.downloads[0].relative_to(workspace) raised ValueError. Default: made on first use (workspace).
		self._workspace = Path(workspace).expanduser().absolute() if workspace else None
		self._agent: Any = None
		self._gateway: ChatBrowserUse | None = None  # set by _build when the model runs on the Browser Use gateway
		self._preflighted = False
		self._model: Any = None
		self._model_name = self._model_ref = self._provider = ''
		self._repl: Repl | None = None
		self._history: list[ModelMessage] | None = None
		self._compacted: dict[str, Any] = {}  # the last run's checkpoint (Compaction): a follow-up keeps sending it
		self._continue = False
		self._runner: asyncio.Runner | None = None  # run_sync's event loop, kept while the REPL lives
		self._running = False
		self._custom_workspace = workspace is not None
		self._downloads: list[Path] = []  # what the last stop() copied from a cloud browser (telemetry counts them)
		self._sync = False  # the current run came from run_sync()
		self._reports = RunReports()  # report_issue() from the REPL, pointed at each run

	@property
	def workspace(self) -> Path:
		"""Default: a new temp dir, made on first use (an Agent that never runs leaves none) and kept after the run
		(the result's files, screenshots, cell output): the caller deletes it (MIGRATING.md). Not deleted on close():
		delivered files and links in the result point into it."""
		if self._workspace is None:
			self._workspace = Path(tempfile.mkdtemp(prefix='browser-use-')).absolute()
		return self._workspace

	def __getattr__(self, name: str) -> Any:
		if name in REMOVED_METHODS:
			raise AttributeError(removed(f'Agent.{name}()', REMOVED_METHODS[name]))
		if name in REMOVED_ATTRS:
			raise AttributeError(removed(f'Agent.{name}', REMOVED_ATTRS[name]))
		raise AttributeError(f'{type(self).__name__!r} object has no attribute {name!r}')

	def add_new_task(self, task: str) -> None:
		"""The next run() continues this conversation with a new task."""
		_check_task_arg(task)
		self.task, self._continue = task, True
		self._tasks.append(task)

	def _check_task(self) -> None:
		if self.browser.use_cloud and (m := LOCAL_TARGET.search(self.task)):  # a hint, never a refusal
			logger.warning(
				f'The task mentions {m.group()!r}; a cloud browser cannot reach your localhost or private network. '
				"If that is the target, use a local browser: Agent(task, browser=Browser('chromium'))."
			)

	def _build(self) -> None:
		model, settings = resolve_model(self.llm)  # raises here, before any browser: missing key or extra
		self._model = model
		self._model_name = getattr(model, 'model_name', str(model))
		system = getattr(model, 'system', None)  # 'anthropic', 'google-gla', ...: prices are looked up per provider
		base_url = str(getattr(model, 'base_url', '') or '')
		if system == 'openai' and base_url and urlparse(base_url).hostname != 'api.openai.com':
			# ChatOpenAI(base_url=...) to DeepSeek, OpenRouter, xAI: the price is the provider's at that URL, not OpenAI's
			with contextlib.suppress(Exception):  # a backend genai-prices does not know: no price, cost_usd None
				system = calc_price(RequestUsage(), model_ref=self._model_name, provider_api_url=base_url).provider.id
		self._model_ref = f'{system}:{self._model_name}' if system and ':' not in self._model_name else self._model_name
		self._gateway = gateway_llm(model)  # any form: ChatBrowserUse, ChatOpenAI(base_url=gateway), pydantic_model()
		if self._gateway:  # cost is only what the gateway charged (charge_usd), never a retail estimate
			self._model_ref = f'browser-use:{self._model_name}'
		self._provider = getattr(self.llm, 'provider', None) or getattr(model, 'system', '')
		self._search = self._web_search()
		if self.reasoning is not None and not reasoning_supported(model):
			logger.warning(
				f'reasoning={self.reasoning!r} is ignored: {self._model_name} gets no reasoning setting. For an '
				'OpenAI-compatible server pass ChatOpenAI(..., reasoning_effort=...) instead.'
			)
		# A bu-* alias carries its own effort (bu-fast medium, bu-ultrafast low, bu-smart high): send none. A listed OpenAI
		# model on the gateway has none of its own: without 'medium' it ran at the upstream default (live: gpt-6-luna
		# high, gpt-6.1-sol xhigh), not at the 'medium' ChatOpenAI sends for the same model.
		alias = bool(self._gateway and self._gateway.model.startswith('bu-'))
		self._agent = build_agent(
			model,
			output_type=self.output_model_schema,
			reasoning_effort=self.reasoning or (None if alias else 'medium'),
			instructions='\n'.join(
				filter(
					None,
					[
						f'{CLOUD_PROMPT} {CAPTCHA_PROMPT if self.browser.captcha_solver else NO_CAPTCHA_PROMPT}'
						if self.browser.use_cloud
						else LOCAL_PROMPT
						if self._launched()
						else '',
						SEARCH_PROMPT if self._search else '',  # off: the default prompt stays byte-identical
						self.browser.domains.prompt(
							browser_blocks=not self.browser._attached()
						),  # '' without restrictions: the default prompt stays byte-identical
						redact(self.extend_system_message, self.sensitive_data),
					],
				)
			),
			max_context_chars=self.max_context_chars,
			mode=self.mode,
			tools=self.tools.functions if self.tools else (),
			model_settings=settings,
		)

	def _web_search(self) -> WebSearch | None:
		"""search() with the key and host of the gateway model, else the Browser Use key and the default gateway host.
		None when off (the default)."""
		if not self.web_search:
			return None
		if self.browser.domains.allowed:
			raise ValueError(
				'Agent(web_search=True) cannot be combined with allowed_domains: search would reach sites the browser may not open'
			)
		gateway = self._gateway
		key = (gateway.api_key if gateway else None) or browser_use_api_key('Agent(web_search=True)')
		return WebSearch(key, search_url(gateway.base_url if gateway else GATEWAY_URL))

	async def run(self, max_steps: int = 100, timeout: float = 1700, **kwargs: Any) -> AgentHistoryList:
		"""Run the current task. max_steps: model requests; as in 0.x the last one is a delivery-only turn (max_steps=1
		only delivers), and one delivery repair may follow it. timeout: seconds for the agent loop (model requests and
		cells); starting the browser before it and stopping it (with cloud downloads) after it are not counted."""
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
		raise_fd_limit()  # before the first socket: many concurrent Agents exceed macOS's default 256 open files
		if self._agent is None:
			self._build()
		started, result, error_type, session, browser_s = time.monotonic(), None, None, None, None
		tools = frozenset(t.name for t in self.tools.functions) if self.tools else frozenset()
		rec = RunRecorder(tools, self._model_name, bool(self._gateway))
		run_id, number, concurrent, phase = uuid.uuid4().hex, next(_RUNS), _ACTIVE[0], 'preflight'
		follow_up = self._continue
		prior = len(self._history or []) if follow_up else 0  # messages of earlier tasks, not counted for this run
		self._downloads = []
		before = set((self.workspace / 'downloads').glob('*'))
		self._telemetry_started(run_id, rec, max_steps, timeout)
		self._reports.start(run_id, rec, model_id(self._model_name), list(dict.fromkeys(self._tasks)), self.sensitive_data)
		_ACTIVE[0] += 1
		try:
			logger.info(f'Task: {redact(self.task, self.sensitive_data)[:200]} (workspace {self.workspace})')
			if self._repl is None:
				check_loop()  # before the browser starts: a cloud browser bills from its create
				# a dead gateway, a rejected key, a bad model or a missing search endpoint fails before any browser starts
				if not self._preflighted:
					model, search = self._model, self._search
					check = self._gateway.preflight if self._gateway else (lambda: provider_preflight(model))
					t = now()
					error = await asyncio.to_thread(lambda: check() or (search and search.preflight()))
					rec.phase('preflight', now() - t)
					if error:
						error_type = 'PreflightError'
						result = self._failed(error, started)
						return result
					self._preflighted = True
				self.workspace.mkdir(parents=True, exist_ok=True)
				for sub in ('.browser-use', 'downloads'):  # an unwritable workspace fails here, before a browser is billed
					(self.workspace / sub).mkdir(exist_ok=True)
			self.browser._downloads_dir = self.workspace / 'downloads'  # a keep_alive browser's later stop() copies there
			phase, t = 'browser_start', now()
			try:
				env = await self.browser.start()  # also on a follow-up: a daemon that died since is started again
				if self._repl is None:  # a browser started for this run, not one a keep_alive Agent reuses
					rec.phase('browser_start', now() - t)
			except (MissingAPIKeyError, BrowserConfigError):
				raise  # setup errors (no key, a profile name that matches none), raised before anything was created
			except Exception as e:  # a failed create (402, 5xx, timeout), or a daemon that could not attach to a billed one
				rec.phase('browser_start', now() - t)
				error_type = type(e).__name__
				result = self._failed(str(e) or error_type, started)  # the preflight's shape; finally stops the browser
				return result
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
					search=self._search,
					downloads=self._list_downloads if self.browser.use_cloud or self._launched() else None,
					highlight_actions=self.highlight_actions,
					feedback=self._reports,
				)
			history, self._continue = (self._history if self._continue else None), False
			compacted = self._compacted if history else {}
			session = Session(
				repl=self._repl, timeout_s=timeout, max_steps=max_steps, vision=self.use_vision, rec=rec, **compacted
			)
			self._reports.stats = session.stats
			phase = 'loop'
			result = await run(
				self._agent,
				self.task,
				session,
				self._model_ref,
				message_history=history,
				explain_error=self._gateway.explain_error if self._gateway else None,
			)
			self._history = session.messages  # raw: result.messages has secrets redacted
			# the judge sees the page as the run left it, before the browser stops
			judged = self.judge and self.use_vision and result.steps
			self._final_page = None
			if judged:
				with contextlib.suppress(TimeoutError):  # a slow page: the thread ends at its socket timeouts
					shot = await asyncio.wait_for(
						asyncio.to_thread(self.browser._screenshot, FINAL_SCREENSHOT_TIMEOUT_S), FINAL_SCREENSHOT_TIMEOUT_S
					)
					self._final_page = BinaryContent(shot, media_type='image/jpeg') if shot else None
			self._compacted = {'checkpoint': session.checkpoint, 'covered': session.covered, 'usage_after': session.usage_after}
			result.output_schema = self.output_model_schema
			if result.status == 'error':
				logger.error(result.error)
			else:
				logger.info(f'{result.status} in {result.steps} steps, {result.duration_s:.0f}s')
			return result
		except BaseException as e:
			error_type = type(e).__name__
			raise
		finally:
			_ACTIVE[0] -= 1
			t, loop_phase = now(), phase
			try:
				phase = 'shutdown'
				self.browser.note_downloads(self.workspace / '.browser-use' / 'downloads.jsonl')
				if not self.browser.keep_alive:
					await self._shutdown()
				else:
					await asyncio.to_thread(self.browser.remember_tab)  # a daemon that dies before the next run reattaches it
					# each run's files land in its own workspace; a cancelled run copies what already finished, within
					# CANCEL_DOWNLOADS_TIMEOUT_S (a file still copying then goes to the next run or browser.stop())
					cancelled = (task := asyncio.current_task()) is not None and task.cancelling() > 0
					if self.browser.use_cloud and self.browser.id:
						deadline = time.monotonic() + browser_module.CANCEL_DOWNLOADS_TIMEOUT_S if cancelled else None
						await self.browser._fetch_downloads(
							self.workspace / 'downloads', self.browser._fetched, self._downloads, self.browser.id, deadline
						)
				if result is not None:
					result.downloads = sorted(
						p for p in set((self.workspace / 'downloads').glob('*')) - before if p.suffix != '.crdownload'
					)
				phase = loop_phase
			finally:
				rec.phase('shutdown', now() - t)
				try:  # after the browser stopped (a cloud browser bills until then); a cancelled judge still sends the event
					if error_type is None:
						await self._judge(result)
				finally:
					meta = {'run_id': run_id, 'rec': rec, 'phase': phase, 'number': number, 'concurrent': concurrent}
					self._capture(
						result, session, error_type, max_steps, timeout, prior, browser_s, time.monotonic() - started, meta
					)

	async def _judge(self, result: AgentHistoryList | None) -> None:
		"""One request to the agent's own model judges a run that took steps (judge=False: none). Its tokens and cost, also
		a failed one's, are added to result.usage and result.cost_usd. A failure is logged and leaves result.judgement
		None: the judge never fails a run."""
		self._judge_cost = None
		if not (self.judge and result is not None and result.steps and self._agent is not None):
			return
		task, context = (redact(t, self.sensitive_data) for t in (self.task, self.judge_context))
		final, self._final_page = self._final_page, None
		judgement, messages = await judge_run(self._agent, task, result, context, self.sensitive_data, final)
		if not messages:
			return
		usage, cost = usage_and_cost(messages, self._model_ref)
		for key, n in usage.items():
			result.usage[key] = result.usage.get(key, 0) + n
		result.cost_usd = None if result.cost_usd is None or cost is None else result.cost_usd + cost
		result.judgement, self._judge_cost = judgement, cost
		if judgement is None:
			return
		verdict = 'success' if judgement.success else f'failure: {judgement.failure_reason or judgement.description}'
		logger.info(f'Judge: {verdict}' + ''.join(f'\n  gotcha: {g}' for g in judgement.gotchas))

	def _failed(self, error: str, started: float) -> AgentHistoryList:
		"""The result of a run that failed before the agent loop (preflight, browser start): status 'error', no steps."""
		error = redact(error, self.sensitive_data)  # a provider's or the cloud's message can quote what it was sent
		logger.error(error)
		usage = {'input': 0, 'output': 0, 'cache_read': 0, 'cache_write': 0, 'requests': 0}
		return AgentHistoryList('error', '', None, 0, time.monotonic() - started, usage, 0.0, None, error, [], None)

	def run_sync(self, max_steps: int = 100, timeout: float = 1700, **kwargs: Any) -> AgentHistoryList:
		"""run() without async. One event loop serves every run_sync() while the REPL lives (Browser(keep_alive=True)),
		because the REPL worker's pipes belong to the loop that started it; close_sync() ends it."""
		if kwargs:
			raise _unsupported(kwargs, 'Agent.run_sync')
		try:
			asyncio.get_running_loop()
		except RuntimeError:
			pass  # no loop running here: run_sync() is the right call
		else:
			raise RuntimeError(
				'run_sync() cannot run inside a running event loop (async code, Jupyter): use `await agent.run()` there.'
			)
		self._runner = self._runner or asyncio.Runner()
		self._sync = True
		try:
			return self._runner.run(self.run(max_steps=max_steps, timeout=timeout))
		finally:
			self._sync = False
			if self._repl is None:
				self._runner.close()
				self._runner = None

	def _launched(self) -> bool:
		"""A local Chrome the Browser launches, whose downloads land in workspace/downloads (Browser('chrome') saves to
		yours)."""
		return self.browser.local and not self.browser._attached()

	async def _list_downloads(self) -> list[dict]:
		"""downloads() in the REPL. A cloud browser's copies of JSON pages the tab displayed are left out, so the worker's
		log so far is read first."""
		self.browser.note_downloads(self.workspace / '.browser-use' / 'downloads.jsonl')
		return await self.browser.list_downloads()

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

	def _config(self, max_steps: int, timeout: float) -> dict[str, Any]:
		"""The run's configuration fields: counts, bools, enums and names, never values or paths."""
		from browser_use.telemetry.stats import cdp_category, host, is_internal, provider_name

		schema = self.output_model_schema
		fields = getattr(schema, 'model_fields', None)
		secrets = scoped_secrets(self.sensitive_data)
		browser = self.browser
		mode = browser.kind  # cloud | chromium | chrome | cdp
		kind = model_kind(self._model)
		system = str(getattr(self._model, 'system', '') or '')
		window = getattr(self._model, 'context_window', None)
		exe = Path(str(browser.executable_path)).name.lower() if browser.executable_path else None
		return {
			'model': model_id(self._model_name),
			'model_provider': provider_name(self._provider),
			'reasoning': self.reasoning,
			'mode': self.mode,
			'max_steps': max_steps,
			'timeout_s': timeout,
			'structured_output': schema is not str,
			'output_schema_fields': len(fields) if isinstance(fields, dict) else None,
			'custom_tools': sorted(t.name for t in self.tools.functions)[:50] if self.tools else [],
			'sensitive_data_count': len({n for n, _, _ in secrets}),
			'sensitive_data_domain_scoped': sum(d is not None for _, _, d in secrets),
			'extend_system_message': bool(self.extend_system_message),
			'custom_workspace': self._custom_workspace,
			'task_chars': len(self.task),
			'browser_mode': mode,
			'cdp_url': cdp_category(host(browser.cdp_url)) if mode == 'cdp' else None,
			'keep_alive': browser.keep_alive,
			'cloud_profile': bool(browser.use_cloud and browser.profile),
			'cloud_proxy_country': browser.proxy if browser.use_cloud else None,
			'cloud_timeout_min': browser.timeout if browser.use_cloud else None,
			'live_view': bool(browser.live_view),
			'domain_restrictions': bool(browser.domains),
			'is_internal': is_internal(),
			'web_search': self.web_search,
			'use_vision': self.use_vision,
			'highlight_actions': self.highlight_actions,
			'judge': self.judge,
			'judge_context': self.judge_context is not None,
			'max_context_chars_set': self.max_context_chars is not None,
			'captcha_solver': browser.captcha_solver if browser.use_cloud else None,
			'headless': browser.headless,
			'chrome_profile': bool(browser.chrome_profile),
			'user_data_dir': bool(browser.user_data_dir),
			'browser_exe': None
			if exe is None
			else 'edge'
			if 'edge' in exe
			else 'chromium'
			if 'chromium' in exe
			else 'chrome'
			if 'chrome' in exe
			else 'other',
			'allowed_domains_n': len(browser.domains.allowed),
			'prohibited_domains_n': len(browser.domains.prohibited),
			'block_ip_addresses': bool(browser.domains.block_ips),
			'gateway': self._gateway is not None,
			'model_api': kind
			if kind != 'other'
			else 'anthropic'
			if system == 'anthropic'
			else 'google'
			if system.startswith('google')
			else 'other',
			'compaction_mode': 'server' if kind == 'responses' else 'client',
			'context_window': window if isinstance(window, int) and not isinstance(window, bool) else None,
			'sync': self._sync,
		}

	def _telemetry_started(self, run_id: str, rec: RunRecorder, max_steps: int, timeout: float) -> None:
		"""A crash marker, so a run whose process dies is still reported (status crashed). Built in the telemetry thread."""
		try:
			from browser_use.telemetry.service import telemetry
			from browser_use.telemetry.views import AgentTelemetryEvent
			from browser_use.utils import get_browser_use_version, get_install_source

			if not telemetry().enabled:
				return
			snapshot = self._config(max_steps, timeout)  # now: the Agent may change before the thread reads it

			def props() -> dict[str, Any]:
				version, source = get_browser_use_version(), get_install_source()
				return AgentTelemetryEvent(version, source, **snapshot, run_id=run_id).properties

			telemetry().run_started(run_id, props, lambda: {'steps': len(rec.steps)})
		except Exception as e:  # - telemetry never breaks a run
			logger.debug('telemetry failed: %s', e)

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
		meta: dict[str, Any],
	) -> None:
		"""One agent_event per run: counts, names, hostnames and classes, the URLs visited without query strings, error
		messages and the final result, scrubbed of secrets and credentials (stats.scrub). Never the task text, typed
		text, code or secrets. Here, on the run's path, only what can change after the run is copied; the event is built
		in the telemetry thread (build())."""
		try:
			from browser_use.telemetry.service import Job, telemetry
			from browser_use.telemetry.stats import (
				MAX_ERROR,
				MAX_ERRORS,
				MAX_RESULT,
				MAX_URL,
				MAX_URLS,
				RunStats,
				download_ext,
				judged,
				scrub,
				top,
			)
			from browser_use.telemetry.views import AgentTelemetryEvent
			from browser_use.utils import get_browser_use_version, get_install_source

			if not telemetry().enabled:
				return
			rec: RunRecorder = meta['rec']
			stats = session.stats if session else RunStats()
			status = (
				result.status if result else 'cancelled' if error_type in ('CancelledError', 'KeyboardInterrupt') else 'error'
			)
			usage = dict(result.usage) if result else {}
			# names only, not the messages: the event waits in the sender (seconds with PostHog slow or down, up to 100
			# events), and a closure over the messages kept every run's history, screenshots included, alive that long
			called: list[str] = []  # tool names the model wrote, mapped to 'invalid' in build() unless ours
			retried: list[str | None] = []  # the tool name of each retry prompt (None for a text reply)
			for m in result.messages[prior:] if result else ():
				if isinstance(m, ModelResponse):
					called += [p.tool_name for p in m.parts if isinstance(p, ToolCallPart)]
				elif isinstance(m, ModelRequest):
					# Pydantic AI 2.66 sends a retry as the call's ToolReturnPart(outcome='retried'); RetryPromptPart is the old form
					retried += [
						p.tool_name
						for p in m.parts
						if isinstance(p, RetryPromptPart) or (isinstance(p, ToolReturnPart) and p.outcome == 'retried')
					]
			downloads = list(self._downloads)
			budget_hit = session.budget_hit if session else None
			phase = meta['phase']
			if status == 'completed':
				phase = None
			elif status in ('timeout', 'max_steps'):
				phase = 'budget'
			elif phase == 'loop':
				phase = rec.where or ('delivery' if session and session.finalizing else 'model')
			config = self._config(max_steps, timeout)
			fields = {
				**config,
				'run_id': meta['run_id'],
				'follow_up': prior > 0,
				'browser_start_seconds': browser_s,
				'status': status,
				'success': result.is_successful() if result else None,
				'max_steps_hit': status == 'max_steps' or budget_hit == 'max_steps',
				'timed_out': status == 'timeout',
				'finish_via': session.finish_via if session and status == 'completed' else None,
				'partial_used': bool(result and status != 'completed' and result.partial is not None),
				'error_type': error_type or (session.error_type if session and status == 'error' else None),
				'output_chars': len(result.text) if result else 0,
				'total_duration_seconds': duration,
				'steps': result.steps if result else 0,
				'model_requests': usage.get('requests', 0),
				'total_input_tokens': usage.get('input', 0),
				'total_output_tokens': usage.get('output', 0),
				'prompt_cached_tokens': usage.get('cache_read', 0),
				'cache_write_tokens': usage.get('cache_write', 0),
				'total_tokens': usage.get('input', 0) + usage.get('output', 0),
				'cost_usd': result.cost_usd if result else None,
				'run_in_process': meta['number'],
				'concurrent_runs': meta['concurrent'],
				'error_phase': phase,
				'budget_hit': budget_hit,
				'feedback_count': self._reports.sent,
			}
			secrets = self.sensitive_data
			# a follow-up's result can quote the first task; the judgement can quote judge_context
			tasks: list[str] = list(dict.fromkeys([*self._tasks, self.task, *filter(None, [self.judge_context])]))
			run_error = result.error if result else None
			final = result.text if result else None
			judgement = result.judgement.model_dump() if result and result.judgement else None
			judge_cost = self._judge_cost
			known = rec.known
			function_tools = known - {'finish', 'finish_from_repl'}
			total_ms = int(duration * 1000)

			def build(steps: int, keys: int) -> dict[str, Any]:
				"""In the telemetry thread: the names the model's code chose are checked here (imports, cdp methods)."""
				from collections import Counter

				# a tool name the model made up can carry task or page text (only names browser-use or you chose)
				tools = Counter(name if name in known else 'invalid' for name in called)
				v3 = rec.build(stats, total_ms, steps, keys)
				if tool_args := sum(name in function_tools for name in retried):
					v3['retries']['tool_args'] = tool_args
				forms = secret_forms(secrets) if secrets else []
				urls = dict.fromkeys(scrub(u, forms, MAX_URL, tasks, stats.typed) for u in stats.urls[: min(keys, MAX_URLS)])
				errors = [
					scrub(e, forms, MAX_ERROR, tasks, stats.typed)
					for e in ([run_error] if run_error else []) + stats.error_messages
				]
				repairs = ('delivery_placeholder', 'delivery_missing_files', 'delivery_split', 'text_repair', 'text_tool_markup')
				event = AgentTelemetryEvent(
					get_browser_use_version(),
					get_install_source(),
					**fields,
					**v3,
					tool_calls=top(tools, keys),
					retry_prompts=len(retried),
					invalid_tool_calls=tools['invalid'],
					delivery_repairs=sum(v3['retries'].get(k, 0) for k in repairs),
					cells=stats.cells,
					cell_errors=stats.cell_errors,
					cell_seconds=round(stats.cell_seconds, 3),
					cell_error_types=top(stats.error_types, keys),
					helper_counts=top(stats.helpers, keys),
					cdp_method_counts=top(stats.cdp_methods, keys),
					imports=top(stats.imports, keys),
					screenshots=stats.images,
					domains=list(top(stats.domains, keys)),
					domain_count=len(stats.domains),
					navigations=stats.navigations,
					captcha_started=stats.events['captcha_started'],
					captcha_solved=stats.events['captcha_solved'],
					captcha_failed=stats.events['captcha_failed'],
					downloads_started=stats.events['download_started'],
					domain_blocks=stats.events['domain_blocked'],
					downloads=len(downloads),
					download_exts=top(Counter(download_ext(p) for p in downloads), keys),
					urls_visited=[u for u in urls if u],
					error_messages=[e for e in dict.fromkeys(errors) if e][:MAX_ERRORS],
					final_result=scrub(final, forms, MAX_RESULT, tasks, stats.typed) or None,
					judgement=judged(judgement, judge_cost, lambda text: scrub(text, forms, MAX_ERROR, tasks, stats.typed)),
				)
				return event.properties

			telemetry().capture_run(Job('agent_event', build, run_id=meta['run_id']))
		except Exception as e:  # - telemetry never breaks a run
			logger.debug('telemetry failed: %s', e)
			with contextlib.suppress(Exception):
				from browser_use.telemetry.service import telemetry

				telemetry().forget(meta['run_id'])


if not TYPE_CHECKING:  # pyright would accept any name imported from here
	from browser_use.legacy import removed_names

	__getattr__ = removed_names(__name__)  # a 0.x name raises the removed error naming its 1.0 answer
