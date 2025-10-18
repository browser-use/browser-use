"""Async-safe logging handler that forwards records to a Textual TUI via asyncio.Queue.

PoC: simple, minimal, not production hardened.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping


class TextualLogHandler(logging.Handler):
    def __init__(self, queue: "asyncio.Queue[dict[str, Any]]") -> None:
        super().__init__()
        self.queue = queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            # get a formatted timestamp using the handler's formatter if present
            try:
                if self.formatter is not None:
                    timestamp = self.formatter.formatTime(record)
                else:
                    timestamp = logging.Formatter().formatTime(record)
            except Exception:
                timestamp = getattr(record, 'asctime', '')

            row = {
                "timestamp": timestamp,
                "level": record.levelname,
                "logger": record.name,
                "message": msg,
            }

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # no running loop — in simple scripts, just put_nowait
                try:
                    self.queue.put_nowait(row)
                except Exception:
                    # fallback to printing if queue is full or unavailable
                    print(msg)
                return

            # schedule put in running loop thread-safely
            loop.call_soon_threadsafe(self.queue.put_nowait, row)

        except Exception:  # pragma: no cover - defensive
            self.handleError(record)

