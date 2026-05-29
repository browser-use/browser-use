"""Run WebVoyager / GAIA tasks in parallel with batched LLM inference.

A pool of ``batch_size`` slots pulls tasks from a queue; each slot drives one
browser-use Agent in its own headed window, all sharing one ``BatchCoordinator``.
When a task finishes or times out, the slot pulls the next task until ``task_num``
are done. ``run_batch`` just runs; ``run_capture`` also records each trajectory.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from browser_use import Agent, Browser, ChatDashScope
from simulator.config import CAPTCHA_NUDGE, RUNS_DIR, RunConfig
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
	browser = Browser(
		headless=False,
		user_data_dir=str(profile_root / f'slot{slot}_{uuid.uuid4().hex[:8]}'),
		max_iframes=15,  # ad-heavy sites (e.g. Allrecipes) have many iframes; cap AX-tree work
	)
	agent = Agent(
		task=task.question,
		llm=llm,
		browser=browser,
		initial_actions=[{'navigate': {'url': task.start_url, 'new_tab': False}}],
		use_vision=cfg.use_vision,
		use_judge=False,
		enable_planning=False,
		calculate_cost=False,
		extend_system_message=CAPTCHA_NUDGE,
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

	result = (history.final_result() or '')[:500] if history is not None else None
	return TaskOutcome(task, slot, status, round(time.time() - t0, 1), result=result, error=err)


def _profile_root() -> Path:
	return Path(tempfile.mkdtemp(prefix='sim_profiles_'))


def _coordinator(cfg: RunConfig) -> BatchCoordinator:
	return BatchCoordinator(ChatDashScope(model=cfg.model), max_batch=cfg.batch_size, max_wait_s=cfg.max_wait)


async def run_batch(cfg: RunConfig) -> list[TaskOutcome]:
	"""Run tasks in parallel with no recording."""
	tasks = load_tasks(cfg.task_num, cfg.shuffle, cfg.seed, cfg.source)
	print(f'Running {len(tasks)} tasks | batch_size={cfg.batch_size} | source={cfg.source} | model={cfg.model}')
	coord = _coordinator(cfg)
	profile_root = _profile_root()

	async def handler(task, slot) -> TaskOutcome:
		print(f'  [slot {slot}] ▶ {task.id}', flush=True)
		outcome = await execute_task(task, slot, BatchLLMProxy(coord), coord, profile_root, cfg)
		print(f'  [slot {slot}] ■ {outcome.status:9s} {outcome.seconds}s  {task.id}', flush=True)
		return outcome

	outcomes = await run_pool(tasks, cfg.batch_size, handler)
	print('\n' + '=' * 64)
	print(f'Completed {len(outcomes)} tasks | LLM batches: {coord.batch_stats()}')
	return outcomes


async def run_capture(cfg: RunConfig, out_dir: Path | None = None) -> Path:
	"""Run tasks in parallel and record each one's full trajectory; returns the run dir."""
	out_dir = out_dir or (RUNS_DIR / f'run_{int(time.time())}')
	out_dir.mkdir(parents=True, exist_ok=True)
	tasks = load_tasks(cfg.task_num, cfg.shuffle, cfg.seed, cfg.source)
	print(f'Capturing {len(tasks)} tasks -> {out_dir} | batch_size={cfg.batch_size} | source={cfg.source}')
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

	outcomes = await run_pool(tasks, cfg.batch_size, handler)
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
