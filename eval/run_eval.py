"""Browser-Use evaluation harness.

Runs a suite of YAML tasks against a configurable browser backend (local chromium,
Browser Use cloud, or an arbitrary CDP endpoint) and a configurable LLM backend, then
reports pass rate alongside a latency breakdown so speed changes can be A/B'd.

Each task runs in its own subprocess so browser sessions never interfere.

Usage:
    python eval/run_eval.py --suite hermetic --profile fast --repeat 3
    python eval/run_eval.py --suite all --browser cloud --out report.json
"""

import argparse
import asyncio
import functools
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent

# Agent settings presets, ordered from most careful to most aggressive.
# These are the primary speed/accuracy tradeoff knobs; the harness exists to quantify them.
PROFILES: dict[str, dict[str, Any]] = {
	'default': {
		'use_vision': True,
		'use_thinking': True,
		'flash_mode': False,
		'max_actions_per_step': 5,
		'max_history_items': None,
	},
	'fast': {
		'use_vision': True,
		'use_thinking': False,
		'flash_mode': True,
		'max_actions_per_step': 8,
		'max_history_items': 8,
	},
	'turbo': {
		'use_vision': False,
		'use_thinking': False,
		'flash_mode': True,
		'max_actions_per_step': 10,
		'max_history_items': 5,
	},
}


# --------------------------------------------------------------------------------------
# Instrumentation
# --------------------------------------------------------------------------------------


class TimingLLM:
	"""Delegating wrapper that accumulates wall time spent inside LLM calls.

	BaseChatModel is a runtime-checkable Protocol, so structural delegation is enough.
	"""

	def __init__(self, inner: Any):
		self._inner = inner
		self.llm_seconds = 0.0
		self.llm_calls = 0
		self.prompt_tokens = 0
		self.completion_tokens = 0

	def __getattr__(self, name: str) -> Any:
		return getattr(self._inner, name)

	@property
	def model(self) -> str:
		return self._inner.model

	@property
	def provider(self) -> str:
		return self._inner.provider

	@property
	def name(self) -> str:
		return self._inner.name

	@property
	def model_name(self) -> str:
		return self._inner.model_name

	async def ainvoke(self, messages, output_format=None, **kwargs):
		started = time.perf_counter()
		try:
			result = await self._inner.ainvoke(messages, output_format, **kwargs)
		finally:
			self.llm_seconds += time.perf_counter() - started
			self.llm_calls += 1
		usage = getattr(result, 'usage', None)
		if usage is not None:
			self.prompt_tokens += getattr(usage, 'prompt_tokens', 0) or 0
			self.completion_tokens += getattr(usage, 'completion_tokens', 0) or 0
		return result


class ObservationTimer:
	"""Accumulates wall time spent building browser state summaries (DOM + screenshot).

	Patches the bound method on the session class for this subprocess only.
	"""

	def __init__(self):
		self.seconds = 0.0
		self.calls = 0
		self._original = None

	def install(self) -> None:
		from browser_use.browser.session import BrowserSession

		if self._original is not None:
			return
		self._original = BrowserSession.get_browser_state_summary

		@functools.wraps(self._original)
		async def timed(session_self, *args, **kwargs):
			started = time.perf_counter()
			try:
				return await self._original(session_self, *args, **kwargs)  # type: ignore[misc]
			finally:
				self.seconds += time.perf_counter() - started
				self.calls += 1

		BrowserSession.get_browser_state_summary = timed  # type: ignore[assignment]

	def uninstall(self) -> None:
		if self._original is None:
			return
		from browser_use.browser.session import BrowserSession

		BrowserSession.get_browser_state_summary = self._original  # type: ignore[assignment]
		self._original = None


# --------------------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------------------


def build_llm(timing: bool = True) -> Any:
	"""Construct the agent LLM from env.

	BU_EVAL_LLM selects the backend:
	  browser-use  -> ChatBrowserUse (hosted gateway, needs BROWSER_USE_API_KEY)
	  openai       -> ChatOpenAI, honours OPENAI_BASE_URL for a Modal-hosted
	                  OpenAI-compatible endpoint
	  google       -> ChatGoogle
	"""
	backend = os.getenv('BU_EVAL_LLM', 'browser-use').lower()

	if backend in ('browser-use', 'browseruse', 'bu'):
		from browser_use import ChatBrowserUse

		api_key = os.getenv('BROWSER_USE_API_KEY')
		if not api_key:
			raise RuntimeError('BROWSER_USE_API_KEY is required for BU_EVAL_LLM=browser-use')
		kwargs: dict[str, Any] = {'api_key': api_key, 'model': os.getenv('BU_EVAL_MODEL', 'bu-2-0-mini-preview')}
		# BROWSER_USE_LLM_URL / base_url lets this point at a self-hosted or Modal gateway.
		if os.getenv('BU_EVAL_LLM_BASE_URL'):
			kwargs['base_url'] = os.getenv('BU_EVAL_LLM_BASE_URL')
		llm = ChatBrowserUse(**kwargs)

	elif backend == 'openai':
		from browser_use import ChatOpenAI

		kwargs = {'model': os.getenv('BU_EVAL_MODEL', 'gpt-4.1-mini')}
		base_url = os.getenv('BU_EVAL_LLM_BASE_URL') or os.getenv('OPENAI_BASE_URL')
		if base_url:
			kwargs['base_url'] = base_url
		llm = ChatOpenAI(**kwargs)

	elif backend == 'google':
		from browser_use.llm.google.chat import ChatGoogle

		llm = ChatGoogle(model=os.getenv('BU_EVAL_MODEL', 'gemini-3.1-flash-lite'))

	else:
		raise RuntimeError(f'Unknown BU_EVAL_LLM={backend!r} (expected browser-use, openai or google)')

	return TimingLLM(llm) if timing else llm


def build_judge() -> Any:
	"""Judge LLM, used only for tasks without expected_substrings."""
	if os.getenv('GOOGLE_API_KEY'):
		from browser_use.llm.google.chat import ChatGoogle

		return ChatGoogle(model=os.getenv('BU_EVAL_JUDGE_MODEL', 'gemini-3.1-flash-lite'))
	if os.getenv('BROWSER_USE_API_KEY'):
		from browser_use import ChatBrowserUse

		return ChatBrowserUse(api_key=os.environ['BROWSER_USE_API_KEY'], model='bu-2-0-mini-preview')
	return None


def build_browser() -> tuple[Any, bool]:
	"""Construct the browser session from env.

	BU_EVAL_BROWSER selects the backend:
	  local  -> chromium launched in-process (or attached via BU_CDP_URL if prewarmed)
	  cloud  -> Browser Use cloud browser
	  cdp    -> attach to BU_CDP_URL (sidecar container, browser grid, ...)

	Returns (session, owns_browser). owns_browser=False means this process attached to a
	browser it did not start, so teardown must stop() rather than kill() it.
	"""
	from browser_use import BrowserProfile, BrowserSession

	backend = os.getenv('BU_EVAL_BROWSER', 'local').lower()
	headless = os.getenv('BU_EVAL_HEADLESS', 'true').lower() not in ('0', 'false', 'no')

	if backend == 'cloud':
		return (
			BrowserSession(
				use_cloud=True,
				cloud_proxy_country_code=os.getenv('BU_EVAL_CLOUD_PROXY') or None,
				cloud_timeout=int(os.getenv('BU_EVAL_CLOUD_TIMEOUT', '120')),
			),
			True,
		)

	if backend == 'cdp':
		cdp_url = os.getenv('BU_CDP_URL')
		if not cdp_url:
			raise RuntimeError('BU_CDP_URL is required for BU_EVAL_BROWSER=cdp')
		# is_local stays False: we attached to a browser we do not own.
		return BrowserSession(browser_profile=BrowserProfile(cdp_url=cdp_url)), False

	if backend != 'local':
		raise RuntimeError(f'Unknown BU_EVAL_BROWSER={backend!r} (expected local, cloud or cdp)')

	# Local: attach to a prewarmed chromium when the entrypoint started one, otherwise launch.
	prewarmed = os.getenv('BU_CDP_URL')
	if prewarmed:
		return BrowserSession(browser_profile=BrowserProfile(cdp_url=prewarmed)), False

	return (
		BrowserSession(
			browser_profile=BrowserProfile(
				headless=headless,
				user_data_dir=None,
				chromium_sandbox=False,
				# Default extensions (uBlock, cookie handlers) cost measurable startup time.
				enable_default_extensions=os.getenv('BU_EVAL_EXTENSIONS', 'false').lower() in ('1', 'true', 'yes'),
			)
		),
		True,
	)


# --------------------------------------------------------------------------------------
# Task running
# --------------------------------------------------------------------------------------


def load_task(path: Path) -> dict[str, Any]:
	data = yaml.safe_load(path.read_text())
	base_url = os.getenv('EVAL_SITE_URL', 'http://127.0.0.1:8000').rstrip('/')
	data['task'] = data['task'].replace('{BASE_URL}', base_url).strip()
	return data


def score_deterministic(output: str, expected: list[str]) -> tuple[bool, str]:
	normalised = output.lower().replace(',', '')
	missing = [e for e in expected if e.lower().replace(',', '') not in normalised]
	if missing:
		return False, f'Missing expected content: {missing}'
	return True, 'All expected substrings present'


async def judge_output(judge: Any, task: str, output: str, criteria: list[str]) -> tuple[bool, str]:
	from pydantic import BaseModel

	from browser_use.llm.messages import UserMessage

	class JudgeResponse(BaseModel):
		success: bool
		explanation: str

	if judge is None:
		return False, 'No judge LLM available (set GOOGLE_API_KEY or BROWSER_USE_API_KEY)'

	criteria_text = '\n- '.join(criteria)
	prompt = f"""You are evaluating a browser agent inside a CI pipeline.

Task given to the agent:
{task}

Agent's final output:
{output or '[No output provided]'}

Success criteria:
- {criteria_text}

Reply in JSON with keys: success (true/false), explanation (string).
"""
	response = await judge.ainvoke([UserMessage(content=prompt)], output_format=JudgeResponse)
	return response.completion.success, response.completion.explanation


async def run_single_task(task_file: Path, profile_name: str) -> dict[str, Any]:
	"""Run one task end to end and return a result record. Never raises."""
	import logging
	import warnings

	logging.getLogger().setLevel(logging.CRITICAL)
	for logger_name in ('browser_use', 'telemetry', 'message_manager', 'bubus'):
		logging.getLogger(logger_name).setLevel(logging.CRITICAL)
	warnings.filterwarnings('ignore')

	record: dict[str, Any] = {
		'file': task_file.name,
		'profile': profile_name,
		'success': False,
		'explanation': '',
	}
	session = None
	owns_browser = True
	observation = ObservationTimer()
	process_started = time.perf_counter()

	try:
		task_data = load_task(task_file)
		record['name'] = task_data.get('name', task_file.stem)
		max_steps = task_data.get('max_steps', 15)

		from browser_use import Agent

		llm = build_llm()
		session, owns_browser = build_browser()
		observation.install()

		settings = dict(PROFILES[profile_name])
		agent = Agent(task=task_data['task'], llm=llm, browser_session=session, **settings)

		agent_started = time.perf_counter()
		history = await agent.run(max_steps=max_steps)
		agent_seconds = time.perf_counter() - agent_started

		output = history.final_result() or ''
		steps = len(history.history)

		expected = task_data.get('expected_substrings')
		if expected:
			success, explanation = score_deterministic(output, expected)
		else:
			success, explanation = await judge_output(
				build_judge(), task_data['task'], output, task_data.get('judge_context', ['The agent must solve the task'])
			)

		step_durations = [h.metadata.duration_seconds for h in history.history if h.metadata]

		record.update(
			{
				'success': success,
				'explanation': explanation,
				'output': output[:500],
				'steps': steps,
				'agent_seconds': round(agent_seconds, 3),
				'process_seconds': round(time.perf_counter() - process_started, 3),
				'llm_seconds': round(getattr(llm, 'llm_seconds', 0.0), 3),
				'llm_calls': getattr(llm, 'llm_calls', 0),
				'observation_seconds': round(observation.seconds, 3),
				'observation_calls': observation.calls,
				'other_seconds': round(agent_seconds - getattr(llm, 'llm_seconds', 0.0) - observation.seconds, 3),
				'mean_step_seconds': round(statistics.mean(step_durations), 3) if step_durations else None,
				'prompt_tokens': getattr(llm, 'prompt_tokens', 0),
				'completion_tokens': getattr(llm, 'completion_tokens', 0),
			}
		)

	except Exception as e:
		record['explanation'] = f'{type(e).__name__}: {e}'
		record['process_seconds'] = round(time.perf_counter() - process_started, 3)

	finally:
		observation.uninstall()
		if session is not None:
			try:
				# Only tear down the browser process if this run started it.
				await (session.kill() if owns_browser else session.stop())
			except Exception:
				pass

	return record


# --------------------------------------------------------------------------------------
# Parent process: fan out, aggregate, report
# --------------------------------------------------------------------------------------


async def run_task_subprocess(task_file: Path, profile_name: str, semaphore: asyncio.Semaphore, run_index: int) -> dict[str, Any]:
	async with semaphore:
		env = os.environ.copy()
		env['PYTHONPATH'] = os.pathsep.join(sys.path)
		proc = await asyncio.create_subprocess_exec(
			sys.executable,
			str(Path(__file__).resolve()),
			'--task',
			str(task_file),
			'--profile',
			profile_name,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE,
			env=env,
		)
		stdout, stderr = await proc.communicate()

		result: dict[str, Any] | None = None
		for line in reversed(stdout.decode().strip().split('\n')):
			line = line.strip()
			if line.startswith('{') and line.endswith('}'):
				try:
					result = json.loads(line)
				except json.JSONDecodeError:
					continue
				break

		if result is None:
			result = {
				'file': task_file.name,
				'profile': profile_name,
				'success': False,
				'explanation': f'Subprocess produced no result (code {proc.returncode}): {stderr.decode()[-400:]}',
			}

		result['run_index'] = run_index
		status = '✅' if result['success'] else '❌'
		print(f'  {status} {result["file"]} (run {run_index + 1}) {result.get("process_seconds", "?")}s')
		return result


def _port_is_open(host: str, port: int) -> bool:
	import socket

	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
		sock.settimeout(0.25)
		return sock.connect_ex((host, port)) == 0


def serve_site(port: int) -> None:
	"""Serve the hermetic test site from a daemon thread in the parent process."""
	import threading
	from functools import partial
	from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

	handler = partial(SimpleHTTPRequestHandler, directory=str(EVAL_DIR / 'site'))
	handler.log_message = lambda *a, **k: None  # type: ignore[attr-defined]
	server = ThreadingHTTPServer(('0.0.0.0', port), handler)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	print(f'Serving hermetic test site on port {port}')


def discover_tasks(suite: str) -> list[Path]:
	dirs = []
	if suite in ('hermetic', 'all'):
		dirs.append(EVAL_DIR / 'tasks' / 'hermetic')
	if suite in ('web', 'all'):
		dirs.append(EVAL_DIR / 'tasks' / 'web')
	files: list[Path] = []
	for d in dirs:
		files.extend(sorted(d.glob('*.yaml')))
	return files


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
	ok = [r for r in results if r.get('success')]

	def agg(key: str) -> dict[str, float] | None:
		values = [r[key] for r in results if isinstance(r.get(key), (int, float))]
		if not values:
			return None
		values.sort()
		return {
			'mean': round(statistics.mean(values), 3),
			'median': round(statistics.median(values), 3),
			'p90': round(values[min(len(values) - 1, int(len(values) * 0.9))], 3),
			'min': round(values[0], 3),
			'max': round(values[-1], 3),
		}

	return {
		'passed': len(ok),
		'total': len(results),
		'pass_rate': round(len(ok) / len(results), 3) if results else 0.0,
		'process_seconds': agg('process_seconds'),
		'agent_seconds': agg('agent_seconds'),
		'llm_seconds': agg('llm_seconds'),
		'observation_seconds': agg('observation_seconds'),
		'other_seconds': agg('other_seconds'),
		'steps': agg('steps'),
		'prompt_tokens': agg('prompt_tokens'),
		'completion_tokens': agg('completion_tokens'),
	}


def print_report(results: list[dict[str, Any]], summary: dict[str, Any], meta: dict[str, Any]) -> None:
	print('\n' + '=' * 100)
	print(f'RESULTS  suite={meta["suite"]}  profile={meta["profile"]}  browser={meta["browser"]}  llm={meta["llm"]}')
	print('=' * 100)

	headers = ['Task', 'OK', 'Steps', 'Wall', 'LLM', 'Obs', 'Other', 'Reason']
	rows = []
	for r in results:
		rows.append(
			[
				f'{r["file"]}#{r.get("run_index", 0) + 1}',
				'✅' if r.get('success') else '❌',
				str(r.get('steps', '-')),
				f'{r.get("agent_seconds", 0):.1f}s' if r.get('agent_seconds') else '-',
				f'{r.get("llm_seconds", 0):.1f}s' if r.get('llm_seconds') else '-',
				f'{r.get("observation_seconds", 0):.1f}s' if r.get('observation_seconds') else '-',
				f'{r.get("other_seconds", 0):.1f}s' if r.get('other_seconds') else '-',
				str(r.get('explanation', ''))[:60],
			]
		)

	widths = [max(len(str(row[i])) for row in [headers] + rows) for i in range(len(headers))]
	print(' | '.join(headers[i].ljust(widths[i]) for i in range(len(headers))))
	print('-+-'.join('-' * w for w in widths))
	for row in rows:
		print(' | '.join(str(row[i]).ljust(widths[i]) for i in range(len(headers))))

	print('\n' + '-' * 100)
	print(f'PASS RATE: {summary["passed"]}/{summary["total"]} ({summary["pass_rate"] * 100:.0f}%)')
	for key in ('agent_seconds', 'llm_seconds', 'observation_seconds', 'other_seconds', 'steps'):
		stats = summary.get(key)
		if stats:
			print(f'{key:22} median={stats["median"]:>7}  mean={stats["mean"]:>7}  p90={stats["p90"]:>7}  max={stats["max"]:>7}')
	print('-' * 100 + '\n')


async def main() -> int:
	parser = argparse.ArgumentParser(description='Browser-Use eval harness')
	parser.add_argument('--suite', choices=['hermetic', 'web', 'all'], default='hermetic')
	parser.add_argument('--profile', choices=list(PROFILES), default='default')
	parser.add_argument('--repeat', type=int, default=1, help='Runs per task, for latency variance')
	parser.add_argument('--parallel', type=int, default=int(os.getenv('BU_EVAL_PARALLEL', '3')))
	parser.add_argument('--out', type=str, default=None, help='Write the JSON report here')
	parser.add_argument('--label', type=str, default='', help='Tag this run for A/B comparison')
	parser.add_argument(
		'--serve',
		choices=['auto', 'always', 'never'],
		default='auto',
		help='Serve the hermetic test site locally (auto: only when needed and the port is free)',
	)
	args = parser.parse_args()

	task_files = discover_tasks(args.suite)
	if not task_files:
		print(f'No task files found for suite={args.suite}')
		return 1

	browser_backend = os.getenv('BU_EVAL_BROWSER', 'local').lower()
	site_url = os.getenv('EVAL_SITE_URL', 'http://127.0.0.1:8000')
	if args.suite in ('hermetic', 'all') and browser_backend == 'cloud':
		host = site_url.split('//')[-1].split(':')[0]
		if host in ('127.0.0.1', 'localhost', '0.0.0.0'):
			print(
				f'ERROR: the hermetic suite serves the test site at {site_url}, which a cloud browser cannot reach.\n'
				'       Expose the site publicly and set EVAL_SITE_URL, or run the hermetic suite with '
				'BU_EVAL_BROWSER=local.'
			)
			return 1

	# A single prewarmed chromium cannot be shared by concurrent tasks: each session would
	# see the others' tabs, and the first teardown would disconnect the rest. Parallel runs
	# fall back to a browser per task.
	if browser_backend == 'local' and os.getenv('BU_CDP_URL') and args.parallel > 1:
		print(f'NOTE: --parallel {args.parallel} with a prewarmed browser is unsafe; each task will launch its own chromium.')
		os.environ.pop('BU_CDP_URL')

	needs_site = args.suite in ('hermetic', 'all')
	site_port = int(site_url.rsplit(':', 1)[-1]) if ':' in site_url.split('//')[-1] else 80
	if args.serve == 'always' or (args.serve == 'auto' and needs_site and not _port_is_open('127.0.0.1', site_port)):
		serve_site(site_port)

	meta = {
		'suite': args.suite,
		'profile': args.profile,
		'browser': browser_backend,
		'llm': os.getenv('BU_EVAL_LLM', 'browser-use'),
		'model': os.getenv('BU_EVAL_MODEL', ''),
		'label': args.label,
		'repeat': args.repeat,
		'started_at': time.time(),
	}

	print(f'Running {len(task_files)} task(s) x {args.repeat} on profile={args.profile} browser={browser_backend}')
	semaphore = asyncio.Semaphore(args.parallel)
	jobs = [
		run_task_subprocess(task_file, args.profile, semaphore, run_index)
		for run_index in range(args.repeat)
		for task_file in task_files
	]
	results = await asyncio.gather(*jobs)

	summary = summarise(list(results))
	print_report(list(results), summary, meta)

	report = {'meta': meta, 'summary': summary, 'results': list(results)}
	out_path = (
		Path(args.out) if args.out else EVAL_DIR / 'reports' / f'{args.suite}-{args.profile}-{int(meta["started_at"])}.json'
	)
	out_path.parent.mkdir(parents=True, exist_ok=True)
	out_path.write_text(json.dumps(report, indent=2))
	print(f'Report written to {out_path}')

	# Fail only on a total wipeout, matching the previous CI harness contract.
	return 1 if summary['total'] > 0 and summary['passed'] == 0 else 0


if __name__ == '__main__':
	pre = argparse.ArgumentParser(add_help=False)
	pre.add_argument('--task', type=str)
	pre.add_argument('--profile', type=str, default='default')
	known, _ = pre.parse_known_args()

	if known.task:
		try:
			result = asyncio.run(run_single_task(Path(known.task), known.profile))
		except Exception as e:
			result = {
				'file': Path(known.task).name,
				'success': False,
				'explanation': f'Critical subprocess error: {type(e).__name__}: {e}',
			}
		print(json.dumps(result))
	else:
		sys.exit(asyncio.run(main()))
