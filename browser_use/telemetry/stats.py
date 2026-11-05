"""What a run reports to telemetry: counts, names, hostnames and classes. Never text that the task, the model, a page or
an exception wrote (TELEMETRY.md). No heavy imports: the REPL worker never imports this module."""

from __future__ import annotations

import ast
import os
import platform
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from functools import cache
from importlib.metadata import PackageNotFoundError, version
from typing import Any
from urllib.parse import urlsplit

MAX_KEYS = 50  # per map or list: a run that visits 10k hosts sends the 50 most frequent
CDP_METHOD = re.compile(r'[A-Za-z][A-Za-z0-9]{0,40}\.[A-Za-z][A-Za-z0-9]{0,60}')  # Domain.method, nothing else
CLI_CONTENT = ('task', 'output', 'steps', 'error_message')  # browser-harness cli_event fields that carry text


def host(url: Any) -> str | None:
	"""The hostname of a URL, lowercased, without user, password, port, path, query or fragment. None without one."""
	try:
		return urlsplit(str(url)).hostname or None
	except ValueError:
		return None


def top(counter: Counter, n: int = MAX_KEYS) -> dict[str, int]:
	return dict(counter.most_common(n))


def imported_modules(code: str) -> list[str]:
	"""Top-level module names a cell imports ('pandas' for `from pandas.io import x`). Nothing else of the code."""
	try:
		tree = ast.parse(code)
	except (SyntaxError, ValueError):
		return []
	names: list[str] = []
	for node in ast.walk(tree):
		if isinstance(node, ast.Import):
			names += [a.name.split('.')[0] for a in node.names]
		elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
			names.append(node.module.split('.')[0])
	return names


def _version(*dists: str) -> str | None:
	for dist in dists:
		try:
			return version(dist)
		except PackageNotFoundError:
			continue
	return None


@cache
def environment() -> dict[str, Any]:
	"""Where browser-use runs; the same for every event of a process."""
	from browser_use.config import is_running_in_docker

	return {
		'os': platform.system() or 'unknown',
		'os_release': platform.release() or None,
		'arch': platform.machine() or 'unknown',
		'python_version': platform.python_version(),
		'pydantic_ai_version': _version('pydantic-ai-slim', 'pydantic-ai'),
		'browser_harness_version': _version('browser-harness'),
		'is_docker': is_running_in_docker(),
		'is_ci': bool(os.getenv('CI') or os.getenv('GITHUB_ACTIONS')),
		'is_notebook': 'ipykernel' in sys.modules,
	}


@dataclass
class RunStats:
	"""Counters for one Agent.run(), filled from each REPL cell's result (worker.py `stats`)."""

	cells: int = 0
	cell_errors: int = 0
	cell_seconds: float = 0.0
	images: int = 0
	navigations: int = 0
	helpers: Counter = field(default_factory=Counter)  # helper name -> calls, e.g. goto_url, bu.click
	cdp_methods: Counter = field(default_factory=Counter)  # raw cdp() calls the agent made, by method
	domains: Counter = field(default_factory=Counter)  # hostname -> cells that saw it
	imports: Counter = field(default_factory=Counter)  # top-level modules cells imported
	error_types: Counter = field(default_factory=Counter)  # exception class of each failed cell
	events: Counter = field(default_factory=Counter)  # captcha_started, captcha_solved, captcha_failed, download_started

	def add_cell(self, result: dict, code: str, seconds: float) -> None:
		self.cells += 1
		self.cell_seconds += seconds
		self.images += len(result.get('images') or [])
		if result.get('error'):
			self.cell_errors += 1
			self.error_types[str(result.get('error_type') or 'unknown')] += 1
		self.imports.update(imported_modules(code))
		s = result.get('stats') or {}
		self.helpers.update(s.get('helpers') or {})
		for method, n in (s.get('cdp') or {}).items():  # the model can pass anything as the method: a URL, code
			self.cdp_methods[method if CDP_METHOD.fullmatch(str(method)) else 'invalid'] += int(n)
		self.domains.update(s.get('hosts') or [])
		self.events.update(s.get('events') or {})
		self.navigations += int(s.get('navigations') or 0)


def scrub_cli_event(payload: dict) -> dict:
	"""A browser-harness event as the browser-use CLI sends it: without the piped code, its output, the helper
	arguments and error text; helper names are kept as counts."""
	props = payload.get('properties')
	if not isinstance(props, dict):
		return payload
	steps = [s for s in props.get('steps') or [] if isinstance(s, dict)]
	clean = {k: v for k, v in props.items() if k not in CLI_CONTENT}
	clean['helper_counts'] = top(Counter(str(s['helper']) for s in steps if s.get('helper'))) or None
	clean['helper_errors'] = sum(1 for s in steps if s.get('error')) if steps else None
	clean['schema_version'] = 2
	return {**payload, 'properties': clean}
