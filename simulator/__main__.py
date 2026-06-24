"""Command-line entry point: python -m simulator <run|capture|eval> ..."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from simulator.config import RunConfig


def _add_run_args(p: argparse.ArgumentParser) -> None:
	# Defaults come from RunConfig so config.py is the single source of truth.
	d = RunConfig()
	p.add_argument('--task-num', type=int, default=d.task_num, help='Total number of tasks to complete.')
	p.add_argument('--batch-size', type=int, default=d.batch_size, help='Concurrent tasks / windows / LLM batch size.')
	p.add_argument('--source', choices=['both', 'webvoyager', 'gaia'], default=d.source, help='Which task set(s) to draw from.')
	p.add_argument('--model', default=d.model, help='DashScope model.')
	p.add_argument('--max-steps', type=int, default=d.max_steps, help='Max agent steps per task.')
	p.add_argument('--task-timeout', type=float, default=d.task_timeout, help='Per-task wall-clock timeout (seconds).')
	p.add_argument('--llm-timeout', type=float, default=d.llm_timeout, help='Per-call LLM timeout (seconds).')
	p.add_argument('--max-wait', type=float, default=d.max_wait, help='Max seconds the coordinator waits to fill a batch.')
	p.add_argument('--shuffle', action='store_true')
	p.add_argument('--seed', type=int, default=d.seed)


def _cfg(a: argparse.Namespace) -> RunConfig:
	return RunConfig(
		task_num=a.task_num,
		batch_size=a.batch_size,
		source=a.source,
		model=a.model,
		max_steps=a.max_steps,
		task_timeout=a.task_timeout,
		llm_timeout=a.llm_timeout,
		max_wait=a.max_wait,
		shuffle=a.shuffle,
		seed=a.seed,
	)


def main() -> None:
	ap = argparse.ArgumentParser(prog='python -m simulator', description='WebVoyager parallel simulator.')
	sub = ap.add_subparsers(dest='cmd', required=True)

	_add_run_args(sub.add_parser('run', help='Run tasks in parallel with batched LLM (no recording).'))

	pc = sub.add_parser('capture', help='Run tasks and capture full trajectories.')
	_add_run_args(pc)
	pc.add_argument('--out-dir', default=None, help='Where to write trajectories (default: simulator/runs/run_<ts>).')

	pe = sub.add_parser('eval', help='Offline evaluation of captured trajectories (no browser, no web).')
	pe.add_argument('path', help='A task folder (with step_*) or a run folder of task folders.')
	pe.add_argument(
		'--mode',
		choices=['success', 'replay'],
		default='success',
		help="'success' = WebVoyager task-success judge (did the task complete?); 'replay' = action fidelity.",
	)
	pe.add_argument(
		'--model',
		default=None,
		help='Judge model for success (default qwen-vl-max) / predict model for replay (default qwen-max).',
	)
	pe.add_argument('--k', type=int, default=2, help='Number of final screenshots given to the success judge.')

	pl = sub.add_parser('latency', help='Replay-mode latency benchmark: batched replay of recorded contexts, no browser.')
	pl.add_argument('path', help='A run folder of captured task trajectories (with <task>/step_*).')
	pl.add_argument('--task-num', type=int, default=8, help='Total tasks to replay to completion.')
	pl.add_argument('--batch-size', type=int, default=4, help='Tasks replayed together per batched server step.')
	pl.add_argument(
		'--start',
		choices=['zero', 'random'],
		default='zero',
		help="Start each task at step 0 ('zero') or a random step ('random'), then replay to its end.",
	)
	pl.add_argument('--seed', type=int, default=0, help='Sampling / random-start seed.')
	pl.add_argument('--max-tokens', type=int, default=1024, help='Max decode tokens per step.')
	pl.add_argument('--temperature', type=float, default=0.0)
	pl.add_argument('--top-k-label', default=None, help='Free-text label for the server top-k setting (recorded in output).')
	pl.add_argument('--out', default=None, help='Output JSON path (default: under the run folder).')

	a = ap.parse_args()
	if a.cmd == 'run':
		from simulator.core import run_batch

		asyncio.run(run_batch(_cfg(a)))
	elif a.cmd == 'capture':
		from simulator.core import run_capture

		asyncio.run(run_capture(_cfg(a), Path(a.out_dir) if a.out_dir else None))
	elif a.cmd == 'eval':
		from simulator.eval import evaluate_path

		asyncio.run(evaluate_path(Path(a.path), mode=a.mode, model=a.model, k=a.k))
	elif a.cmd == 'latency':
		from simulator.eval.latency import measure_latency

		asyncio.run(
			measure_latency(
				Path(a.path),
				task_num=a.task_num,
				batch_size=a.batch_size,
				start_mode=a.start,
				seed=a.seed,
				max_tokens=a.max_tokens,
				temperature=a.temperature,
				top_k_label=a.top_k_label,
				out=Path(a.out) if a.out else None,
			)
		)


if __name__ == '__main__':
	main()
