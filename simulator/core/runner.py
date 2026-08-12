"""Run WebVoyager / GAIA tasks in parallel with batched LLM inference.

A pool of ``batch_size`` slots pulls tasks from a queue; each slot drives one
browser-use Agent in its own headed window, all sharing one ``BatchCoordinator``.
When a task finishes or times out, the slot pulls the next task until ``task_num``
are done. ``run_batch`` just runs; ``run_capture`` also records each trajectory.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from browser_use import Agent, Browser, ChatDashScope
from browser_use.llm.openai.chat import ChatOpenAI
from simulator.config import COMBINED_NUDGE, RUNS_DIR, TSA_API_KEY, TSA_BASE_URL, TSA_MODEL, USE_TSA, RunConfig
from simulator.core.batching import BatchCoordinator, BatchLLMProxy
from simulator.core.recorder import RecordingProxy, TrajectoryRecorder
from simulator.tasks import WebVoyagerTask, load_tasks

T = TypeVar('T')
R = TypeVar('R')


async def run_pool(items: list[T], concurrency: int, handler: Callable[[T, int], Awaitable[R]]) -> list[R]:
	"""Run ``handler(item, slot)`` over ``items`` with at most ``concurrency`` in flight."""
	queue: asyncio.Queue[T] = asyncio.Queue()
	for it in items:
		queue.put_nowait(it)
	results: list[R] = []

	async def worker(slot: int) -> None:
		while True:
			try:
				item = queue.get_nowait()
			except asyncio.QueueEmpty:
				return
			results.append(await handler(item, slot))

	await asyncio.gather(*(worker(i) for i in range(concurrency)))
	return results


@dataclass(slots=True)
class TaskOutcome:
	task: WebVoyagerTask
	slot: int
	status: str  # 'completed' | 'timeout' | 'error'
	seconds: float
	steps: int | None = None
	result: str | None = None
	error: str | None = None
	extra: dict[str, Any] = field(default_factory=dict)


async def execute_task(
	task: WebVoyagerTask,
	slot: int,
	llm,
	coord: BatchCoordinator,
	profile_root: Path,
	cfg: RunConfig,
	*,
	on_step_start: Callable[[Agent], Awaitable[None]] | None = None,
	on_finish: Callable[[Agent, str, bool | None], None] | None = None,
) -> TaskOutcome:
	"""Run one task in its own headed window with a wall-clock timeout, then clean up."""
	udir = profile_root / f'slot{slot}_{uuid.uuid4().hex[:8]}'
	browser = Browser(
		headless=os.environ.get('SIM_HEADLESS', '0').lower() not in ('0', 'false', 'no', ''),  # SIM_HEADLESS=1 for big headless batch runs
		user_data_dir=str(udir),
		enable_default_extensions=False,
		max_iframes=15,  # ad-heavy sites (e.g. Allrecipes) have many iframes; cap AX-tree work
	)
	agent = Agent(
		task=task.question,
		llm=llm,
		browser=browser,
		initial_actions=[{'navigate': {'url': task.start_url, 'new_tab': False}}],
		# SIM_NO_VISION=1 runs the agent TEXT-ONLY (no screenshots to the LLM) — used for
		# sparse-attention experiments where the vision KV would confound the comparison.
		use_vision=cfg.use_vision and os.environ.get('SIM_NO_VISION', '0').lower() not in ('1', 'true'),
		llm_screenshot_size=(1280, 720),  # downscale the per-step vision image (full-HD PNGs are ~3MB each)
		use_judge=False,
		enable_planning=False,
		llm_timeout=cfg.llm_timeout,
		calculate_cost=False,
		extend_system_message=COMBINED_NUDGE,  # CAPTCHA route-around + done-guard + anti-loop (30B fix experiment)
		# generous per-step timeout for slow batched calls on the GB10 (override via SIM_STEP_TIMEOUT)
		step_timeout=int(os.environ.get('SIM_STEP_TIMEOUT', '360')),
	)

	t0 = time.time()
	status, success, history, err = 'error', None, None, None
	coord.enter()  # this agent now contributes to each batch until it finishes
	try:
		history = await asyncio.wait_for(
			agent.run(max_steps=cfg.max_steps, on_step_start=on_step_start), timeout=cfg.task_timeout
		)
		status, success = 'completed', history.is_successful()
	except asyncio.TimeoutError:
		status, success = 'timeout', None
	except Exception as e:  # noqa: BLE001
		status, success, err = 'error', False, str(e)[:300]
	finally:
		coord.leave()  # stop expecting this agent; release any batch waiting on it
		if on_finish is not None:
			try:
				on_finish(agent, status, success)
			except Exception:  # noqa: BLE001
				pass
		try:
			await browser.kill()
		except Exception:  # noqa: BLE001
			pass
		# Delete this task's browser profile (Chrome caches ~40MB each); otherwise profiles
		# accumulate under the temp dir and fill the disk over a long run.
		shutil.rmtree(udir, ignore_errors=True)

	result = (history.final_result() or '')[:500] if history is not None else None
	return TaskOutcome(task, slot, status, round(time.time() - t0, 1), result=result, error=err)


def _profile_root() -> Path:
	return Path(tempfile.mkdtemp(prefix='sim_profiles_'))


def _build_llm(cfg: RunConfig):
	"""The agent LLM. Defaults to the spark01 TreeSparseAttention server; set
	USE_TSA=0 to fall back to DashScope/Qwen."""
	if USE_TSA:
		# TSA is OpenAI-compatible but has no server-side json_schema enforcement
		# (xgrammar absent), so request structured output via the system prompt and
		# parse JSON from the text instead of relying on response_format.
		return ChatOpenAI(
			model=TSA_MODEL,
			base_url=TSA_BASE_URL,
			api_key=TSA_API_KEY,
			temperature=0.2,
			max_completion_tokens=1024,  # bound decode: agent output is ~300-600 tok; 1024 keeps decode ~150s (<240s llm-timeout) on the GB10 even with default thinking
			add_schema_to_system_prompt=True,
			dont_force_structured_output=False,  # send response_format=json_schema -> server xgrammar grammar-constrained decoding (valid JSON even under aggressive sparsity)
		)
	# temperature/max_completion_tokens match the reference request format
	return ChatDashScope(model=cfg.model, temperature=0.2, max_completion_tokens=4096)


def _coordinator(cfg: RunConfig) -> BatchCoordinator:
	llm = _build_llm(cfg)
	return BatchCoordinator(llm, max_batch=cfg.batch_size, max_wait_s=cfg.max_wait)


async def run_batch(cfg: RunConfig) -> list[TaskOutcome]:
	"""Run tasks in parallel with no recording."""
	tasks = load_tasks(cfg.task_num, cfg.shuffle, cfg.seed, cfg.source)
	print(f'Running {len(tasks)} tasks | batch_size={cfg.batch_size} | source={cfg.source} | model={TSA_MODEL if USE_TSA else cfg.model}')
	coord = _coordinator(cfg)
	profile_root = _profile_root()

	async def handler(task, slot) -> TaskOutcome:
		print(f'  [slot {slot}] ▶ {task.id}', flush=True)
		outcome = await execute_task(task, slot, BatchLLMProxy(coord), coord, profile_root, cfg)
		print(f'  [slot {slot}] ■ {outcome.status:9s} {outcome.seconds}s  {task.id}', flush=True)
		return outcome

	outcomes = await run_pool(tasks, cfg.batch_size, handler)
	shutil.rmtree(profile_root, ignore_errors=True)  # remove the temp profile root (per-task slot dirs already cleaned)
	print('\n' + '=' * 64)
	print(f'Completed {len(outcomes)} tasks | LLM batches: {coord.batch_stats()}')
	return outcomes


async def run_capture(cfg: RunConfig, out_dir: Path | None = None) -> Path:
	"""Run tasks in parallel and record each one's full trajectory; returns the run dir."""
	out_dir = out_dir or (RUNS_DIR / f'run_{int(time.time())}')
	out_dir.mkdir(parents=True, exist_ok=True)
	tasks = load_tasks(cfg.task_num, cfg.shuffle, cfg.seed, cfg.source)

	# Resume support: skip tasks already captured. A folder counts as captured only if it has a
	# final 'completed'/'timeout' status AND at least one step recorded a real model output — a
	# 'completed' status alone can mask a degenerate run (e.g. the initial navigation timed out and
	# every step no-op'd), which we must retry rather than silently accept. resume re-runs 'error'/missing.
	def _already_captured(task: WebVoyagerTask) -> bool:
		folder = out_dir / task.folder_name
		mp = folder / 'meta.json'
		if not mp.exists():
			return False
		try:
			if json.loads(mp.read_text()).get('status') not in ('completed', 'timeout'):
				return False
		except Exception:  # noqa: BLE001
			return False
		return any(folder.glob('step_*/output.json'))  # a real trajectory has >=1 recorded model output

	# SIM_TASK_IDS=<json file>: restrict the run to an explicit task subset (list of
	# {"id":..., "source":...} or folder-name strings). Used for controlled experiments.
	ids_file = os.environ.get('SIM_TASK_IDS')
	if ids_file:
		raw = json.loads(Path(ids_file).read_text())
		want = {r if isinstance(r, str) else f'{r["source"]}__{r["id"]}' for r in raw}
		tasks = [t for t in tasks if t.folder_name in want]
		print(f'SIM_TASK_IDS: restricted to {len(tasks)} tasks from {ids_file}')

	todo = [t for t in tasks if not _already_captured(t)]
	skipped = len(tasks) - len(todo)
	print(f'Capturing {len(todo)} tasks ({skipped} already captured) -> {out_dir} | batch_size={cfg.batch_size} | source={cfg.source}')
	if not todo:
		print('all tasks already captured — nothing to do')
		return out_dir
	coord = _coordinator(cfg)
	profile_root = _profile_root()

	async def handler(task, slot) -> TaskOutcome:
		recorder = TrajectoryRecorder(out_dir / task.folder_name, task)
		print(f'  [slot {slot}] ▶ {task.id}', flush=True)
		outcome = await execute_task(
			task,
			slot,
			RecordingProxy(coord, recorder),
			coord,
			profile_root,
			cfg,
			on_step_start=recorder.on_step_start,
			on_finish=recorder.finalize,
		)
		outcome.steps = recorder.step
		outcome.extra['dir'] = str(out_dir / task.folder_name)
		print(f'  [slot {slot}] ■ {outcome.status} steps={recorder.step} -> {task.folder_name}', flush=True)
		return outcome

	outcomes = await run_pool(todo, cfg.batch_size, handler)
	shutil.rmtree(profile_root, ignore_errors=True)  # remove the temp profile root (per-task slot dirs already cleaned)
	summary = [
		{
			'id': o.task.id,
			'site': o.task.site,
			'source': o.task.source,
			'status': o.status,
			'steps': o.steps,
			'dir': o.extra.get('dir'),
		}
		for o in outcomes
	]
	(out_dir / 'run_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
	print('\n' + '=' * 64)
	print(f'Captured {len(outcomes)} task trajectories under {out_dir}')
	for o in outcomes:
		print(f'  {o.status:9s} steps={o.steps}  {o.task.id}')
	print(f'LLM batches: {coord.batch_stats()}')
	return out_dir
