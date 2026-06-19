"""Shared helpers for offline evaluation (no browser, no live web)."""

from __future__ import annotations

import os
from pathlib import Path

from openai import AsyncOpenAI

from simulator.config import DASHSCOPE_BASE_URL


def client() -> AsyncOpenAI:
	# Prefer the local TreeSparseAttention server (same deployed model) when USE_TSA,
	# so eval works without a DashScope key and is consistent with the reference self-judge.
	from simulator.config import TSA_API_KEY, TSA_BASE_URL, USE_TSA

	if USE_TSA:
		return AsyncOpenAI(api_key=TSA_API_KEY, base_url=TSA_BASE_URL)
	if 'DASHSCOPE_API_KEY' not in os.environ:
		raise SystemExit('Set DASHSCOPE_API_KEY')
	return AsyncOpenAI(api_key=os.environ['DASHSCOPE_API_KEY'], base_url=DASHSCOPE_BASE_URL)


def find_task_dirs(root: Path) -> list[Path]:
	"""Accept either a single task folder (has step_*) or a run folder of task folders."""
	if any(root.glob('step_*')):
		return [root]
	return sorted(d for d in root.iterdir() if d.is_dir() and any(d.glob('step_*')))
