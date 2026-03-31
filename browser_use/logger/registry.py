# logger_registry.py

from pathlib import Path
from .service import EventLogger 
# logger_registry.py addition
from contextvars import ContextVar

_current_task_id: ContextVar[str] = ContextVar("current_task_id")
_loggers: dict[str, EventLogger] = {}

def set_current_task(task_id: str):
    _current_task_id.set(task_id)

def get_current_logger() -> EventLogger:
    """Get the logger for whichever task is running in this async context."""
    task_id = _current_task_id.get()  # raises LookupError if not set
    return get_logger(task_id)

def get_logger(task_id: str) -> EventLogger:
    """Retrieve an existing logger for this task_id."""
    if task_id not in _loggers:
        raise KeyError(f"No logger registered for task_id '{task_id}'")
    return _loggers[task_id]


def register_logger(task_id: str, log_dir: str | Path = "logs") -> EventLogger:
    """Create and register a new logger for this task_id."""
    path = Path(log_dir) / f"events_{task_id}.json"
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