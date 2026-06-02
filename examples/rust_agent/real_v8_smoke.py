"""Run one real_v8 benchmark task through the Rust-backed Browser Use Agent.

Set BROWSER_USE_TERMINAL_BINARY when the terminal binary is not on PATH.
Set BU_CDP_URL or BROWSER_USE_CDP_URL to attach to a remote Browser Use cloud browser.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from browser_use import Agent, BrowserSession


DEFAULT_DATASET = Path('/home/exedev/Developer/terminal/datasets/real_v8.json')


def load_cases(dataset: Path) -> list[dict[str, str]]:
	with dataset.open(encoding='utf-8') as file:
		raw_cases = json.load(file)
	if not isinstance(raw_cases, list):
		raise ValueError(f'{dataset} must contain a JSON array')

	cases: list[dict[str, str]] = []
	for idx, raw_case in enumerate(raw_cases):
		if not isinstance(raw_case, dict):
			raise ValueError(f'{dataset} case {idx} must be an object')
		task_id = raw_case.get('task_id')
		task = raw_case.get('confirmed_task') or raw_case.get('task')
		if not isinstance(task_id, str) or not isinstance(task, str) or not task.strip():
			raise ValueError(f'{dataset} case {idx} must contain string task_id and confirmed_task')
		cases.append({'task_id': task_id, 'confirmed_task': task})
	return cases


def select_case(cases: list[dict[str, str]], *, index: int | None, task_id: str | None) -> dict[str, str]:
	if index is not None and task_id is not None:
		raise ValueError('Select by index or task_id, not both')
	if task_id is not None:
		for case in cases:
			if case['task_id'] == task_id:
				return case
		raise ValueError(f'task_id {task_id!r} was not found')
	selected_index = 0 if index is None else index
	if selected_index < 0 or selected_index >= len(cases):
		raise ValueError(f'index {selected_index} is outside dataset range 0..{len(cases) - 1}')
	return cases[selected_index]


def _int_from_env(name: str, default: int) -> int:
	value = os.environ.get(name)
	return int(value) if value else default


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		'--dataset',
		type=Path,
		default=Path(os.environ.get('REAL_V8_DATASET', DEFAULT_DATASET)),
		help='Path to real_v8.json.',
	)
	parser.add_argument(
		'--index',
		type=int,
		default=int(os.environ['REAL_V8_INDEX']) if os.environ.get('REAL_V8_INDEX') else None,
		help='Zero-based case index. Defaults to 0 when --task-id is not set.',
	)
	parser.add_argument(
		'--task-id',
		default=os.environ.get('REAL_V8_TASK_ID'),
		help='Task id from the dataset.',
	)
	parser.add_argument(
		'--max-steps',
		type=int,
		default=_int_from_env('BU_MAX_STEPS', 40),
		help='Maximum Rust terminal agent turns.',
	)
	parser.add_argument(
		'--cdp-url',
		default=os.environ.get('BU_CDP_URL') or os.environ.get('BROWSER_USE_CDP_URL'),
		help='Optional remote browser CDP endpoint.',
	)
	parser.add_argument('--list', action='store_true', help='Print task ids and first task line, then exit.')
	return parser.parse_args()


async def run_smoke(args: argparse.Namespace) -> None:
	cases = load_cases(args.dataset)
	if args.list:
		for idx, case in enumerate(cases):
			first_line = case['confirmed_task'].strip().splitlines()[0]
			print(f'{idx}\t{case["task_id"]}\t{first_line[:120]}')
		return

	case = select_case(cases, index=args.index, task_id=args.task_id)
	browser_session = BrowserSession(cdp_url=args.cdp_url) if args.cdp_url else None
	agent = Agent(task=case['confirmed_task'], browser_session=browser_session, task_id=case['task_id'])
	history = await agent.run(max_steps=args.max_steps)
	final_result = history.final_result()
	print(json.dumps(_summary(case, final_result, history.is_successful(), agent), indent=2))


def _summary(case: dict[str, str], final_result: str | None, is_successful: bool | None, agent: Any) -> dict[str, Any]:
	errors = [error for error in agent.history.errors() if error]
	return {
		'task_id': case['task_id'],
		'successful': is_successful,
		'session_id': agent.session_id,
		'final_result': final_result,
		'errors': errors,
		'urls': agent.history.urls(),
	}


if __name__ == '__main__':
	asyncio.run(run_smoke(parse_args()))
