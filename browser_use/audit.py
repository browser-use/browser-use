"""Opt-in JSONL evidence for an aligned agent; never a tamper-proof security boundary."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from browser_harness.recorder import _scrub_url

from browser_use.repl.session import Secrets, secret_forms


class AuditLog:
	def __init__(self, path: str | Path, secrets: Secrets | None = None):
		self.path = Path(path).expanduser().resolve()
		self.path.parent.mkdir(parents=True, exist_ok=True)
		self.forms = [form for form, _ in secret_forms(secrets or {})]
		# Fail before starting a browser if the destination is unwritable.
		with self.path.open('a', encoding='utf-8'):
			pass

	def write(self, event: str, target_id: str | None = None, **details) -> None:
		def clean(value):
			if isinstance(value, str):
				for form in self.forms:
					value = value.replace(form, '[REDACTED]')
				return _scrub_url(value)
			if isinstance(value, dict):
				return {clean(k): clean(v) for k, v in value.items()}
			if isinstance(value, (list, tuple)):
				return [clean(v) for v in value]
			return value

		line = json.dumps(clean(dict(ts=time.time(), event=event, target_id=target_id, **details)), ensure_ascii=True) + '\n'
		# One append write, shared with the worker and guard (including after worker restarts).
		fd = os.open(self.path, os.O_WRONLY | os.O_APPEND)
		try:
			os.write(fd, line.encode('utf-8'))
		finally:
			os.close(fd)
