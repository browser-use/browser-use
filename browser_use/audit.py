"""Opt-in JSONL evidence for an aligned agent; never a tamper-proof security boundary."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

from browser_harness.recorder import _scrub_url

from browser_use.repl.session import Secrets, scoped_secrets, secret_forms


class AuditLog:
	def __init__(self, path: str | Path, secrets: Secrets | None = None):
		self.path = Path(path).expanduser().resolve()
		self.path.parent.mkdir(parents=True, exist_ok=True)
		forms = [form for form, _ in secret_forms(secrets or {}, include_short_encodings=True)]
		patterns = [re.escape(form) for form in forms]
		for _, value, _ in scoped_secrets(secrets or {}):
			if not value:
				continue
			patterns.append(f'(?i:{value.encode().hex()})')
			for encoded in (urllib.parse.quote(value, safe=''), urllib.parse.quote_plus(value)):
				# Only the hex digits of percent escapes are case-insensitive; literal URL text is not.
				parts = re.split(r'(%[0-9A-Fa-f]{2})', encoded)
				patterns.append(''.join(f'(?i:{part})' if part.startswith('%') else re.escape(part) for part in parts))
		self.pattern = re.compile('|'.join(patterns)) if patterns else None
		# A marker must not itself contain a secret (for example, REDACTED).
		self.marker = next((m for m in ('[REDACTED]', '[***]') if not self.pattern or not self.pattern.search(m)), None)
		# Fail before starting a browser if the destination is unwritable.
		with self.path.open('a', encoding='utf-8'):
			pass

	def write(self, event: str, target_id: str | None = None, **details) -> None:
		def clean(value: Any) -> Any:
			if isinstance(value, str):
				value = _scrub_url(value)
				if not self.pattern:
					return value
				marker = self.marker
				if marker is None:
					return None
				value = self.pattern.sub(lambda _: marker, value)
				# Substitution can join surrounding text into another secret form.
				return marker if self.pattern.search(value) else value
			if isinstance(value, dict):
				return {k: clean(v) for k, v in value.items()}
			if isinstance(value, (list, tuple)):
				return [clean(v) for v in value]
			return value

		line = (
			json.dumps(dict(ts=time.time(), event=event, target_id=clean(target_id), **clean(details)), ensure_ascii=True) + '\n'
		)
		# One append write, shared with the worker and guard (including after worker restarts).
		fd = os.open(self.path, os.O_WRONLY | os.O_APPEND)
		try:
			os.write(fd, line.encode('utf-8'))
		finally:
			os.close(fd)
