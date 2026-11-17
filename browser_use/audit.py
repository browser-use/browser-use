"""Opt-in JSONL evidence for an aligned agent; never a tamper-proof security boundary."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

from browser_harness.recorder import _scrub_url

from browser_use.repl.session import Secrets, scoped_secrets, secret_forms

logger = logging.getLogger(__name__)


class AuditLog:
	def __init__(self, path: str | Path, secrets: Secrets | None = None):
		self._disabled = False
		self.path = Path(path).expanduser().resolve()
		self.path.parent.mkdir(parents=True, exist_ok=True)
		if secrets is not None and not isinstance(secrets, dict | list | tuple):
			secrets = list(secrets)  # read twice below; a one-shot iterator would miss the second pass
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
		# Fail before starting a browser if the destination is unwritable.
		fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
		try:
			os.chmod(self.path, 0o600)
		finally:
			os.close(fd)

	def write(self, event: str, target_id: str | None = None, **details) -> None:
		if self._disabled:
			return

		def clean(value: Any, redact: bool = False) -> Any:
			if isinstance(value, str):
				value = _scrub_url(value)
				return self.pattern.sub('[REDACTED]', value) if redact and self.pattern else value
			if isinstance(value, dict):
				return {clean(k, redact): clean(v, redact) for k, v in value.items()}
			if isinstance(value, (list, tuple)):
				return [clean(v, redact) for v in value]
			return value

		def serialize(record: dict) -> str:
			return json.dumps(record, ensure_ascii=False) + '\n'

		try:
			record = dict(ts=time.time(), event=event, target_id=target_id)
			line = serialize({**record, **clean(details)})
			if self.pattern and self.pattern.search(line):
				line = serialize({**record, **clean(details, redact=True)})
				if self.pattern.search(line):
					line = serialize({**record, 'redacted': True})
				if self.pattern.search(line):
					raise ValueError('Unsafe audit record')
			fd = os.open(self.path, os.O_WRONLY | os.O_APPEND)
			try:
				data = line.encode('utf-8')
				if os.write(fd, data) != len(data):
					raise OSError('Partial audit write')
			finally:
				os.close(fd)
		except (OSError, TypeError, ValueError) as exc:
			if isinstance(exc, OSError):
				# A failed append may leave partial bytes; never join another record onto them.
				self._disabled = True
			# Evidence is best effort: an append failure must never bypass enforcement.
			# Exception text can contain record data, so do not log it.
			logger.warning('Audit record could not be written')
