"""Per-task EventLogger registry keyed by an async-context task id.

The runner (e.g. web-knowledge run_agent.py) calls `register_logger(task_id, dir)`
and `set_current_task(task_id)` before starting the agent; the tools registry then
emits action/element events through `get_current_logger()` without any plumbing.
"""

from contextvars import ContextVar
from pathlib import Path

from .service import EventLogger

_current_task_id: ContextVar[str] = ContextVar('current_task_id')
_loggers: dict[str, EventLogger] = {}


def set_current_task(task_id: str):
	_current_task_id.set(task_id)


def get_current_logger() -> EventLogger:
	"""Get the logger for whichever task is running in this async context."""
	task_id = _current_task_id.get()  # raises LookupError if not set
	return get_logger(task_id)


def try_get_current_logger() -> EventLogger | None:
	"""Like get_current_logger, but returns None when no task/logger is registered.

	Lets the tools registry treat event capture as strictly optional: callers that
	never registered a logger (plain library users, tests) pay no cost and see no
	errors.
	"""
	try:
		return get_current_logger()
	except (LookupError, KeyError):
		return None


def get_logger(task_id: str) -> EventLogger:
	"""Retrieve an existing logger for this task_id."""
	if task_id not in _loggers:
		raise KeyError(f"No logger registered for task_id '{task_id}'")
	return _loggers[task_id]


def register_logger(task_id: str, log_dir_or_path: str | Path = 'logs') -> EventLogger:
	"""Create and register a new logger for this task_id."""
	path = Path(log_dir_or_path)
	if path.suffix == '':
		path = path / f'event_{task_id}.json'
	logger = EventLogger(path)
	_loggers[task_id] = logger
	return logger


def unregister_logger(task_id: str) -> None:
	"""Clean up after a task finishes."""
	logger = _loggers.pop(task_id, None)
	if logger:
		logger.close()


def current_task_ids() -> list[str]:
	return list(_loggers.keys())
