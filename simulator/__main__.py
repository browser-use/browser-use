"""Command-line entry point: python -m simulator <run|capture|eval> ..."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from simulator.config import DEFAULT_MODEL, RunConfig


def _add_run_args(p: argparse.ArgumentParser) -> None:
	p.add_argument('--task-num', type=int, default=2, help='Total number of tasks to complete.')
	p.add_argument('--batch-size', type=int, default=2, help='Concurrent tasks / windows / LLM batch size.')
	p.add_argument('--source', choices=['both', 'webvoyager', 'gaia'], default='both', help='Which task set(s) to draw from.')
	p.add_argument('--model', default=DEFAULT_MODEL, help='DashScope model.')
	p.add_argument('--max-steps', type=int, default=15, help='Max agent steps per task.')
	p.add_argument('--task-timeout', type=float, default=180.0, help='Per-task wall-clock timeout (seconds).')
	p.add_argument('--max-wait', type=float, default=8.0, help='Max seconds the coordinator waits to fill a batch.')
	p.add_argument('--shuffle', action='store_true')
	p.add_argument('--seed', type=int, default=0)


def _cfg(a: argparse.Namespace) -> RunConfig:
	return RunConfig(
		task_num=a.task_num,
		batch_size=a.batch_size,
		source=a.source,
		model=a.model,
		max_steps=a.max_steps,
		task_timeout=a.task_timeout,
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


if __name__ == '__main__':
	main()
