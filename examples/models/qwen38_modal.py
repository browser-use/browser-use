"""Run a local Browser Use agent against Qwen3.8-27B on Modal.

Set QWEN38_DFLASH2_BASE_URL and QWEN38_DFLASH2_API_KEY for your endpoint.
See qwen38_demo.md for setup, the Amazon task, and inference configuration.

Optional environment variables:

	BROWSER_USE_TASK="Open example.com and report its heading."
	BROWSER_USE_HEADLESS=true
	QWEN38_DFLASH2_BASE_URL=https://your-endpoint.example/v1
	QWEN38_DFLASH2_MODEL=Qwen/Qwen3.8-27B-FP8
	QWEN38_DFLASH2_REASONING_EFFORT=none
	QWEN38_DFLASH2_THINKING_NORMAL_SENTENCES=3
	QWEN38_DFLASH2_THINKING_MAX_SENTENCES=6
	QWEN38_DFLASH2_FULL_BROWSER_CAPABILITIES=false

Run from the repository root with:

	uv run examples/models/qwen38_modal.py

Paste a multiline task, then enter END on its own line.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

import httpx
from dotenv import load_dotenv

from browser_use import Agent, Browser, ChatOpenAI, Tools

load_dotenv()

DEFAULT_MODEL = 'Qwen/Qwen3.8-27B-FP8'
DEFAULT_REASONING_EFFORT = 'none'
DEFAULT_THINKING_NORMAL_SENTENCES = 3
DEFAULT_THINKING_MAX_SENTENCES = 6
MAX_COMPLETION_TOKENS = 1_024
AGENT_TEMPERATURE = 0.3
REPETITION_PENALTY = 1.0
FALLBACK_COMPLETION_TOKENS = 2_048
FALLBACK_REPETITION_PENALTY = 1.08
JUDGE_COMPLETION_TOKENS = 1_024
JUDGE_REASONING_EFFORT = 'none'
JUDGE_REPETITION_PENALTY = 1.0
MAX_ACTIONS_PER_STEP = 5
MAX_AGENT_STEPS = 100
LLM_SCREENSHOT_SIZE = (960, 768)
MAX_CLICKABLE_ELEMENTS_LENGTH = 12_000
MAX_HISTORY_ITEMS: int | None = 6
JUDGE_MAX_IMAGES = 1
HISTORY_SCREENSHOT_INTERVAL = 1_000
LEAN_DOM_ATTRIBUTES = [
	'title',
	'type',
	'checked',
	'id',
	'name',
	'role',
	'value',
	'placeholder',
	'alt',
	'aria-label',
	'aria-expanded',
	'data-state',
	'aria-checked',
	'selected',
	'expanded',
	'disabled',
	'invalid',
	'haspopup',
	'required',
	'busy',
	'href',
]
DEFAULT_TASK = (
	'Open https://example.com. Use the evaluate action with code '
	"`document.title + ' || ' + document.querySelector('h1').textContent`, then report the two exact values."
)
_llm_request_count = 0


FAST_NAVIGATION_EXCLUDED_ACTIONS = [
	'wait',
	'upload_file',
	'save_as_pdf',
	'write_file',
	'replace_file',
	'read_file',
	'extract',
	'search',
]


def build_tools(*, full_browser_capabilities: bool) -> Tools:
	"""Build either the small navigation schema or Browser Use's complete toolset."""
	if full_browser_capabilities:
		return Tools()
	return Tools(exclude_actions=FAST_NAVIGATION_EXCLUDED_ACTIONS)


class TimingProfiler:
	"""Print a wall-clock breakdown for every Browser Use agent step."""

	def __init__(self) -> None:
		self.run_started_at: float | None = None
		self.step_started_at: float | None = None
		self.step_number: int | None = None
		self.step_phases: dict[str, float] = {}
		self.phase_totals: dict[str, float] = {}
		self.completed_step_seconds = 0.0

	def start_run(self) -> None:
		"""Start the overall run timer."""
		self.run_started_at = time.perf_counter()

	async def on_step_start(self, agent: Agent) -> None:
		"""Start timing a Browser Use step."""
		now = time.perf_counter()
		if self.run_started_at is not None and self.step_number is None:
			print(f'\n⏱️  Browser startup + initial actions: {now - self.run_started_at:.2f}s', flush=True)
		self.step_started_at = now
		self.step_number = agent.state.n_steps
		self.step_phases = {}

	async def on_step_end(self, _agent: Agent) -> None:
		"""Print the phase breakdown for a completed Browser Use step."""
		if self.step_started_at is None or self.step_number is None:
			return
		total = time.perf_counter() - self.step_started_at
		self.completed_step_seconds += total
		accounted = sum(self.step_phases.values())
		other = max(0.0, total - accounted)
		parts = [f'{name}={duration:.2f}s' for name, duration in self.step_phases.items()]
		parts.append(f'other={other:.2f}s')
		print(f'⏱️  STEP {self.step_number} TOTAL={total:.2f}s | ' + ' | '.join(parts), flush=True)
		self.step_started_at = None

	def instrument_agent(self, agent: Agent) -> None:
		"""Wrap Browser Use phases and tool execution with wall-clock timers."""
		for method_name, label in (
			('_prepare_context', 'context+screenshot'),
			('_get_next_action', 'llm+parse'),
			('_execute_actions', 'actions'),
			('_post_process', 'post_process'),
			('_finalize', 'finalize'),
			('_judge_and_log', 'judge'),
		):
			self._wrap_phase(agent, method_name, label)

		original_act = agent.tools.act

		async def timed_act(*args: Any, **kwargs: Any) -> Any:
			action = kwargs.get('action') or (args[0] if args else None)
			action_data = action.model_dump(exclude_unset=True) if action is not None else {}
			action_name = next(iter(action_data), 'unknown')
			started_at = time.perf_counter()
			try:
				return await original_act(*args, **kwargs)
			finally:
				print(f'⏱️  ACTION {action_name}: {time.perf_counter() - started_at:.2f}s', flush=True)

		agent.tools.act = timed_act  # type: ignore[method-assign]

	def _wrap_phase(self, agent: Agent, method_name: str, label: str) -> None:
		"""Wrap one async Agent method and attribute its duration to the active step."""
		original_method = getattr(agent, method_name)

		async def timed_phase(*args: Any, **kwargs: Any) -> Any:
			started_at = time.perf_counter()
			try:
				return await original_method(*args, **kwargs)
			finally:
				duration = time.perf_counter() - started_at
				self.phase_totals[label] = self.phase_totals.get(label, 0.0) + duration
				if self.step_started_at is not None:
					self.step_phases[label] = self.step_phases.get(label, 0.0) + duration
				else:
					print(f'⏱️  {label.upper()}: {duration:.2f}s', flush=True)

		setattr(agent, method_name, timed_phase)

	def print_run_total(self) -> None:
		"""Print total wall time and time outside normal agent steps."""
		if self.run_started_at is None:
			return
		total = time.perf_counter() - self.run_started_at
		non_step = max(0.0, total - self.completed_step_seconds)
		print(f'\n⏱️  RUN TOTAL={total:.2f}s | steps={self.completed_step_seconds:.2f}s | outside_steps={non_step:.2f}s')
		ordered = ('llm+parse', 'context+screenshot', 'actions', 'post_process', 'finalize', 'judge')
		breakdown = [
			f'{label}={self.phase_totals[label]:.2f}s ({self.phase_totals[label] / total * 100:.1f}%)'
			for label in ordered
			if self.phase_totals.get(label)
		]
		if breakdown:
			print('⏱️  RUN BREAKDOWN | ' + ' | '.join(breakdown), flush=True)


def parse_args() -> argparse.Namespace:
	"""Parse command-line options for the local demo."""
	parser = argparse.ArgumentParser(description='Run a local Browser Use task with Qwen3.8 on Modal.')
	tasks = parser.add_mutually_exclusive_group()
	tasks.add_argument('--task', help='Task text. If omitted, the CLI opens a multiline paste prompt.')
	tasks.add_argument('--task-file', type=Path, help='Read a UTF-8 task file.')
	parser.add_argument('--chromium', action='store_true', help='Use the Chromium installed by Playwright.')
	parser.add_argument('--keep-open', action='store_true', help='Wait for Enter before closing a browser launched by this demo.')
	parser.add_argument(
		'--full-browser-capabilities',
		action='store_true',
		help='Enable waits, downloads, cross-origin iframes, file/PDF tools, extraction, and external search.',
	)
	return parser.parse_args()


def read_task(cli_task: str | None) -> str:
	"""Resolve a task from the CLI, environment, or an interactive multiline prompt."""
	if cli_task:
		return cli_task

	environment_task = os.getenv('BROWSER_USE_TASK')
	if environment_task:
		return environment_task

	print('Paste your Browser Use task below.')
	print('When finished, enter END on its own line:\n')
	lines: list[str] = []
	while True:
		try:
			line = input()
		except EOFError:
			break
		if line == 'END':
			break
		lines.append(line)

	task = '\n'.join(lines).strip()
	return task or DEFAULT_TASK


def read_api_key() -> str:
	"""Read the Modal API key without storing it in the repository."""
	api_key = os.getenv('QWEN38_DFLASH2_API_KEY')
	if api_key:
		return api_key
	raise ValueError('Set QWEN38_DFLASH2_API_KEY in your environment or local .env file.')


def env_flag(name: str, *, default: bool = False) -> bool:
	"""Read a boolean environment variable."""
	value = os.getenv(name)
	if value is None:
		return default
	return value.lower() in {'1', 'true', 'yes', 'on'}


def reasoning_effort() -> Literal['none', 'low', 'medium', 'xhigh']:
	"""Read and validate the reasoning effort supported by this Qwen endpoint."""
	value = os.getenv('QWEN38_DFLASH2_REASONING_EFFORT', DEFAULT_REASONING_EFFORT).lower()
	if value not in {'none', 'low', 'medium', 'xhigh'}:
		raise ValueError('QWEN38_DFLASH2_REASONING_EFFORT must be none, low, medium, or xhigh')
	return cast(Literal['none', 'low', 'medium', 'xhigh'], value)


def thinking_sentence_limit() -> int:
	"""Read the visible structured-thinking ceiling for genuinely hard states."""
	value = int(os.getenv('QWEN38_DFLASH2_THINKING_MAX_SENTENCES', str(DEFAULT_THINKING_MAX_SENTENCES)))
	if value < 1:
		raise ValueError('QWEN38_DFLASH2_THINKING_MAX_SENTENCES must be at least 1')
	return value


def thinking_normal_sentences() -> int:
	"""Read the target number of visible reasoning sentences for ordinary states."""
	value = int(os.getenv('QWEN38_DFLASH2_THINKING_NORMAL_SENTENCES', str(DEFAULT_THINKING_NORMAL_SENTENCES)))
	if value < 1:
		raise ValueError('QWEN38_DFLASH2_THINKING_NORMAL_SENTENCES must be at least 1')
	return value


def max_history_items() -> int | None:
	"""Read the history window; `none` preserves an append-only cacheable trace."""
	value = os.getenv('QWEN38_DFLASH2_MAX_HISTORY_ITEMS', str(MAX_HISTORY_ITEMS)).strip().lower()
	if value in {'none', 'all', 'unbounded'}:
		return None
	parsed = int(value)
	if parsed <= 5:
		raise ValueError('QWEN38_DFLASH2_MAX_HISTORY_ITEMS must be greater than 5 or `none`')
	return parsed


def print_structured_thinking(_browser_state: Any, model_output: Any, step_number: int) -> None:
	"""Print the bounded, visible reasoning field returned by the Flash agent."""
	thinking = model_output.current_state.thinking
	if thinking:
		print(f'💭 STRUCTURED THINKING — STEP {step_number}: {thinking}', flush=True)


async def mark_request_start(request: httpx.Request) -> None:
	"""Record and print inference request size before waiting for Qwen."""
	global _llm_request_count
	_llm_request_count += 1
	request.extensions['qwen_request_number'] = _llm_request_count
	request.extensions['qwen_request_started_at'] = time.perf_counter()
	request_bytes = len(request.content)
	image_count = 0
	try:
		payload = json.loads(request.content)
		for message in payload.get('messages') or []:
			content = message.get('content')
			if isinstance(content, list):
				image_count += sum(part.get('type') == 'image_url' for part in content if isinstance(part, dict))
	except (TypeError, ValueError):
		pass
	print(
		f'\n⏱️  LLM #{_llm_request_count} START | payload={request_bytes / 1024:.1f} KiB | images={image_count}',
		flush=True,
	)


async def print_reasoning_response(response: httpx.Response) -> None:
	"""Print Qwen's complete hidden reasoning and request metrics."""
	if not response.request.url.path.endswith('/chat/completions'):
		return

	await response.aread()
	try:
		payload = response.json()
	except ValueError:
		return

	choices = payload.get('choices') or []
	message = choices[0].get('message') if choices else None
	reasoning = message.get('reasoning_content') if message else None
	usage = payload.get('usage') or {}
	details = usage.get('completion_tokens_details') or {}
	reasoning_tokens = details.get('reasoning_tokens', usage.get('reasoning_tokens'))
	started_at = response.request.extensions.get('qwen_request_started_at')
	duration = time.perf_counter() - started_at if isinstance(started_at, float) else None
	request_number = response.request.extensions.get('qwen_request_number', '?')
	completion_tokens = usage.get('completion_tokens')
	end_to_end_tps = (
		completion_tokens / duration if isinstance(completion_tokens, int) and duration is not None and duration > 0 else None
	)
	visible_tokens = (
		completion_tokens - reasoning_tokens if isinstance(completion_tokens, int) and isinstance(reasoning_tokens, int) else None
	)

	print('\n' + '━' * 88)
	print(f'🧠 QWEN HIDDEN REASONING — LLM #{request_number}')
	print('━' * 88)
	print(reasoning.strip() if reasoning else '[No reasoning_content returned by the server]')
	print('━' * 88)
	metrics = [
		f'HTTP {response.status_code}',
		f'{duration:.2f}s' if duration is not None else None,
		f'prompt={usage.get("prompt_tokens")} tok' if usage.get('prompt_tokens') is not None else None,
		f'completion={usage.get("completion_tokens")} tok' if usage.get('completion_tokens') is not None else None,
		f'reasoning={reasoning_tokens} tok' if reasoning_tokens is not None else None,
		f'visible≈{visible_tokens} tok' if visible_tokens is not None else None,
		f'end-to-end={end_to_end_tps:.1f} tok/s' if end_to_end_tps is not None else None,
	]
	print(' | '.join(metric for metric in metrics if metric is not None))
	print('━' * 88 + '\n', flush=True)


async def wait_for_inference(client: httpx.AsyncClient, base_url: str, api_key: str, model: str) -> None:
	"""Wait up to five minutes for a cold endpoint before consuming agent steps."""
	deadline = time.monotonic() + 300
	print('Warming inference (cold GPU startup can take several minutes)...', flush=True)
	while (remaining := deadline - time.monotonic()) > 0:
		try:
			response = await client.post(
				f'{base_url.rstrip("/")}/chat/completions',
				headers={'Authorization': f'Bearer {api_key}'},
				json={
					'model': model,
					'messages': [{'role': 'user', 'content': 'Reply OK.'}],
					'max_tokens': 8,
					'temperature': 0,
					'reasoning_effort': 'none',
				},
				timeout=min(20, remaining),
			)
			if response.status_code not in {408, 429, 500, 502, 503, 504}:
				response.raise_for_status()
				data = response.json()
				if not data.get('choices') or not data['choices'][0].get('message', {}).get('content'):
					raise ValueError('Inference endpoint returned no completion during warm-up.')
				print('Inference ready.', flush=True)
				return
		except (httpx.TimeoutException, httpx.ConnectError):
			pass
		await asyncio.sleep(max(0, min(10, deadline - time.monotonic())))
	raise TimeoutError('Inference did not become ready within five minutes; check the Modal deployment.')


async def main(task: str, *, full_browser_capabilities: bool = False, chromium: bool = False, keep_open: bool = False) -> bool:
	api_key = read_api_key()
	base_url = os.getenv('QWEN38_DFLASH2_BASE_URL')
	if not base_url:
		raise ValueError('Set QWEN38_DFLASH2_BASE_URL to your OpenAI-compatible endpoint URL ending in /v1.')
	cdp_url = os.getenv('BROWSER_USE_CDP_URL')
	if chromium and cdp_url:
		raise ValueError('Use --chromium or BROWSER_USE_CDP_URL, not both.')
	executable_path = os.getenv('BROWSER_USE_EXECUTABLE_PATH')
	if chromium:
		try:
			from playwright.async_api import async_playwright  # pyright: ignore[reportMissingImports]
		except ImportError as exc:
			raise ValueError('Run with: uv run --with playwright examples/models/qwen38_modal.py --chromium') from exc
		async with async_playwright() as playwright:
			executable_path = playwright.chromium.executable_path
		if not Path(executable_path).is_file():
			raise ValueError('Install Chromium first: uv run --with playwright playwright install chromium')
	full_browser_capabilities = full_browser_capabilities or env_flag('QWEN38_DFLASH2_FULL_BROWSER_CAPABILITIES')
	tools = build_tools(full_browser_capabilities=full_browser_capabilities)
	model = os.getenv('QWEN38_DFLASH2_MODEL', DEFAULT_MODEL)
	effort = reasoning_effort()
	thinking_normal = thinking_normal_sentences()
	thinking_sentences = thinking_sentence_limit()
	history_items = max_history_items()
	if thinking_normal > thinking_sentences:
		raise ValueError('QWEN38_DFLASH2_THINKING_NORMAL_SENTENCES cannot exceed the maximum')
	async with httpx.AsyncClient() as warmup_client:
		await wait_for_inference(warmup_client, base_url, api_key, model)
	structured_thinking_instruction = (
		f'For this deployment, write exactly {thinking_normal} short `thinking` sentences in ordinary states and '
		f'at most {thinking_sentences} in genuinely hard or contradictory states. Do not emit a separate memory field. '
	)
	modal_session_id = f'qwen38-browser-use-{uuid4().hex}'
	http_client = httpx.AsyncClient(
		timeout=300,
		limits=httpx.Limits(
			max_connections=4,
			max_keepalive_connections=4,
			keepalive_expiry=60.0,
		),
		event_hooks={
			'request': [mark_request_start],
			'response': [print_reasoning_response],
		},
	)
	llm = ChatOpenAI(
		model=model,
		base_url=base_url,
		api_key=api_key,
		reasoning_effort=effort,
		# Send Qwen's non-thinking switch through extra_body so ChatOpenAI does
		# not discard temperature. Native hidden reasoning is replaced by the
		# agent's small visible `thinking` field.
		reasoning_models=[],
		temperature=AGENT_TEMPERATURE,
		top_p=0.8,
		frequency_penalty=None,
		extra_body={
			'reasoning_effort': effort,
			'top_k': 20,
			'repetition_penalty': REPETITION_PENALTY,
			# JSON-object grammar is much lighter than the full schema grammar that
			# previously caused runaway whitespace, but it prevents prose, fences,
			# and Qwen's native <tool_call> serialization at generation time.
			'response_format': {'type': 'json_object'},
		},
		# SGLang's constrained JSON decoder occasionally emits thousands of
		# whitespace/repeated tokens after a valid-looking answer. Put the schema
		# in the prompt and let Browser Use validate the returned JSON instead.
		add_schema_to_system_prompt=True,
		dont_force_structured_output=True,
		# Agent responses should be short. This prevents rare runaway JSON
		# generations from blocking a step for tens of seconds.
		max_completion_tokens=MAX_COMPLETION_TOKENS,
		timeout=300,
		max_retries=3,
		default_headers={'Modal-Session-ID': modal_session_id},
		http_client=http_client,
	)
	fallback_llm = ChatOpenAI(
		model=model,
		base_url=base_url,
		api_key=api_key,
		reasoning_effort=effort,
		reasoning_models=[],
		temperature=AGENT_TEMPERATURE,
		top_p=0.8,
		frequency_penalty=None,
		# If the primary generation still hits its guardrail, retry once in
		# the same agent step with a stronger anti-repetition setting.
		extra_body={
			'reasoning_effort': effort,
			'top_k': 20,
			'repetition_penalty': FALLBACK_REPETITION_PENALTY,
			'response_format': {'type': 'json_object'},
		},
		add_schema_to_system_prompt=True,
		dont_force_structured_output=True,
		max_completion_tokens=FALLBACK_COMPLETION_TOKENS,
		timeout=300,
		max_retries=3,
		default_headers={'Modal-Session-ID': modal_session_id},
		http_client=http_client,
	)
	judge_llm = ChatOpenAI(
		model=model,
		base_url=base_url,
		api_key=api_key,
		reasoning_effort=JUDGE_REASONING_EFFORT,
		reasoning_models=[],
		temperature=AGENT_TEMPERATURE,
		top_p=0.8,
		frequency_penalty=None,
		extra_body={
			'reasoning_effort': JUDGE_REASONING_EFFORT,
			'top_k': 20,
			'repetition_penalty': JUDGE_REPETITION_PENALTY,
			'response_format': {'type': 'json_object'},
		},
		add_schema_to_system_prompt=True,
		dont_force_structured_output=True,
		max_completion_tokens=JUDGE_COMPLETION_TOKENS,
		timeout=300,
		max_retries=3,
		default_headers={'Modal-Session-ID': modal_session_id},
		http_client=http_client,
	)
	browser = Browser(
		cdp_url=cdp_url,
		executable_path=executable_path,
		keep_alive=bool(cdp_url) or keep_open,
		headless=env_flag('BROWSER_USE_HEADLESS'),
		# The navigation profile removes the 500 ms download-detection grace from
		# ordinary clicks. Full mode preserves download-capable Browser Use behavior.
		accept_downloads=full_browser_capabilities,
		wait_between_actions=0.0,
		# Do not delay every page with background traffic. A targeted post-click
		# state-change poll below handles the stale-DOM case that affects correctness.
		wait_for_network_idle_page_load_time=0.0,
		# This is an element-agnostic reliability option for animated native/ARIA dialogs.
		prefer_javascript_clicks_in_dialogs=True,
		cross_origin_iframes=full_browser_capabilities,
	)
	profiler = TimingProfiler()
	completed = False
	try:
		print(
			f'\n⚙️  endpoint={base_url}\n'
			f'⚙️  model={model} | native_reasoning={effort} | '
			f'structured_thinking={thinking_normal} sentences normally/<={thinking_sentences} hard | '
			f'memory=off/thought-history={history_items or "all"} | lightning_mode=on | json_mode=on | '
			f'temperature={AGENT_TEMPERATURE}\n'
			f'⚙️  vision=auto/{LLM_SCREENSHOT_SIZE[0]}x{LLM_SCREENSHOT_SIZE[1]} | '
			f'capabilities={"full" if full_browser_capabilities else "fast-navigation"} | '
			f'max_actions_per_step={MAX_ACTIONS_PER_STEP} | max_steps={MAX_AGENT_STEPS} | '
			f'max_output={MAX_COMPLETION_TOKENS} tok | repetition_penalty={REPETITION_PENALTY} | '
			f'truncation_retry={FALLBACK_COMPLETION_TOKENS} tok/{FALLBACK_REPETITION_PENALTY} | '
			f'clicks=verified/dialog-js/adaptive-600ms | loading_settle=800ms | fixed_network_wait=off | '
			f'wait_tool={"on" if full_browser_capabilities else "off"} | '
			f'downloads={"on" if full_browser_capabilities else "off"} | '
			f'cross_origin_iframes={"on" if full_browser_capabilities else "off"} | '
			f'dom_attrs={len(LEAN_DOM_ATTRIBUTES)} | history_screenshot_every={HISTORY_SCREENSHOT_INTERVAL} steps | '
			f'judge=on/{JUDGE_MAX_IMAGES} images/reasoning={JUDGE_REASONING_EFFORT}\n',
			flush=True,
		)
		agent = Agent(
			task=task,
			llm=llm,
			fallback_llm=fallback_llm,
			judge_llm=judge_llm,
			browser=browser,
			tools=tools,
			use_vision='auto',
			vision_detail_level='low',
			llm_screenshot_size=LLM_SCREENSHOT_SIZE,
			flash_mode=True,
			flash_mode_thinking=True,
			use_judge=True,
			judge_max_images=JUDGE_MAX_IMAGES,
			judge_capture_final_state=True,
			enable_planning=False,
			max_actions_per_step=MAX_ACTIONS_PER_STEP,
			max_history_items=history_items,
			max_failures=3,
			message_compaction=False,
			display_files_in_done_text=False,
			include_attributes=LEAN_DOM_ATTRIBUTES,
			max_clickable_elements_length=MAX_CLICKABLE_ELEMENTS_LENGTH,
			history_screenshot_interval=HISTORY_SCREENSHOT_INTERVAL,
			loading_shell_max_wait_seconds=0.8,
			loading_shell_poll_interval_seconds=0.15,
			post_click_state_settle_max_wait_seconds=0.6,
			post_click_state_settle_poll_interval_seconds=0.1,
			extend_system_message=(
				structured_thinking_instruction
				+ 'Optimize latency only after evidence and user constraints are satisfied. Combine actions only when later actions '
				'do not depend on an unverified page change. Prefer direct navigation only when the destination URL is known from '
				'current evidence or can be constructed without guessing. Do not deliberate about the step budget. '
				'Transient loading shells are refreshed internally before you are called; avoid blind waits when observable state '
				'can establish readiness. A delivered interaction is not proof of its intended outcome. Before leaving a state after '
				'a consequential interaction such as submitting, saving, changing a selection, or adding/removing data, require '
				'visible confirmation or verified resulting state. If an outcome is uncertain, re-observe once; do not repeat the '
				'action blindly. If a commit click remains unchanged, switch to a stable evidence-based route such as the item detail '
				'page instead of trying neighboring controls. Use one focused read-only DOM query only when the needed fact is absent '
				'from normal state; never use a broad wildcard selector to re-read information already visible. Then consume its read_state '
				'on the next step. Result numbers returned by DOM query tools are not interactive element indexes; only use indexes '
				'from the latest browser-state element list for click/input actions. If a delivered click leaves the observable state '
				'unchanged, never repeat that identical click without new evidence. If the user forbids authentication and the only '
				'verified path requires it, report that blocker '
				'immediately rather than retrying or attempting credentials.'
			),
			register_new_step_callback=print_structured_thinking,
		)
		profiler.instrument_agent(agent)
		profiler.start_run()
		try:
			history = await agent.run(
				max_steps=MAX_AGENT_STEPS,
				on_step_start=profiler.on_step_start,
				on_step_end=profiler.on_step_end,
			)
		finally:
			profiler.print_run_total()
		print(f'\nFinal result: {history.final_result()}')
		completed = True
		return history.is_successful() is True
	finally:
		await http_client.aclose()
		try:
			if completed and keep_open and not cdp_url and not env_flag('BROWSER_USE_HEADLESS') and sys.stdin.isatty():
				await asyncio.to_thread(input, '\nBrowser left open. Press Enter to close it...')
		finally:
			if cdp_url:
				await browser.stop()
			else:
				await browser.kill()


if __name__ == '__main__':
	arguments = parse_args()
	task = arguments.task_file.read_text(encoding='utf-8').strip() if arguments.task_file else read_task(arguments.task)
	if not task:
		raise SystemExit('Task must not be empty.')
	success = asyncio.run(
		main(
			task,
			full_browser_capabilities=arguments.full_browser_capabilities,
			chromium=arguments.chromium,
			keep_open=arguments.keep_open,
		)
	)
	raise SystemExit(0 if success else 1)
