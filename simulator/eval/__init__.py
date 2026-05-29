"""Offline evaluation: WebVoyager task-success judging + action-replay fidelity."""

from pathlib import Path

from simulator.eval.replay import evaluate_replay
from simulator.eval.success import evaluate_success

__all__ = ['evaluate_success', 'evaluate_replay', 'evaluate_path']


def evaluate_path(path: Path, mode: str = 'success', model: str | None = None, k: int = 2):
	"""Dispatch to the success judge (default) or the action-replay eval."""
	if mode == 'success':
		from simulator.config import DEFAULT_JUDGE_MODEL

		return evaluate_success(path, model or DEFAULT_JUDGE_MODEL, k)
	if mode == 'replay':
		from simulator.config import DEFAULT_MODEL

		return evaluate_replay(path, model or DEFAULT_MODEL)
	raise SystemExit(f"unknown eval mode: {mode!r} (use 'success' or 'replay')")
