"""What a run reports to telemetry: counts, names, hostnames and classes. Never text that the task, the model, a page or
an exception wrote (TELEMETRY.md). Names the model's code can choose (imported modules, exception classes, cdp()
methods) are kept only when Python, an installed package or the CDP protocol defines them."""

from __future__ import annotations

import ast
import ipaddress
import os
import platform
import sys
from collections import Counter
from dataclasses import dataclass, field
from functools import cache
from importlib.metadata import PackageNotFoundError, packages_distributions, version
from typing import Any
from urllib.parse import urlsplit

MAX_KEYS = 50  # per map or list: a run that visits 10k hosts sends the 50 most frequent
MAX_NAME = 64  # characters per name
CLI_CONTENT = ('task', 'output', 'steps', 'error_message')  # browser-harness cli_event fields that carry text


def host(url: Any) -> str | None:
	"""The hostname of a URL, lowercased, without user, password, port, path, query or fragment. None without one."""
	try:
		return urlsplit(str(url)).hostname or None
	except ValueError:
		return None


def top(counter: Counter, n: int = MAX_KEYS) -> dict[str, int]:
	return dict(counter.most_common(n))


def cdp_category(hostname: str | None) -> str | None:
	"""Where a CDP endpoint is, never its hostname: a Browser Use cloud browser's hostname is its id, and that alone
	drives the browser. browser-use-cloud | localhost | private | public-other."""
	if not hostname:
		return None
	h = hostname.lower().rstrip('.').strip('[]')
	if h == 'browser-use.com' or h.endswith('.browser-use.com'):
		return 'browser-use-cloud'
	if h == 'localhost' or h.endswith('.localhost'):
		return 'localhost'
	try:
		ip = ipaddress.ip_address(h)
	except ValueError:  # a name: one label (docker compose 'chrome') or a local suffix is a private network
		return 'private' if '.' not in h or h.endswith(('.local', '.internal', '.lan', '.home.arpa')) else 'public-other'
	return 'localhost' if ip.is_loopback else 'private' if ip.is_private or ip.is_link_local else 'public-other'


@cache
def _known_modules() -> frozenset[str]:
	"""Top-level modules of the standard library, browser-use and every installed distribution."""
	return frozenset(sys.stdlib_module_names) | frozenset(packages_distributions()) | {'browser_use'}


def imported_modules(code: str) -> list[str]:
	"""Top-level modules a cell imports ('pandas' for `from pandas.io import x`); 'other' for one that is neither in
	the standard library nor installed (a module the model wrote can have any name). Nothing else of the code."""
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
	return [n if n in _known_modules() else 'other' for n in names]


def error_class(e: BaseException) -> str:
	"""The exception's class name when Python, the standard library or an installed package defines it; 'custom' for
	a class the model's code defined, which could be named anything."""
	cls = type(e)
	module = sys.modules.get(cls.__module__ or '')
	known = (cls.__module__ or '').split('.')[0] in _known_modules() and getattr(module, cls.__name__, None) is cls
	return cls.__name__[:MAX_NAME] if known else 'custom'


@cache
def _cdp_methods() -> frozenset[str]:
	"""Every CDP protocol method (cdp-use's generated clients), plus Browser Use cloud's own."""
	try:
		from cdp_use.cdp.library import CDPLibrary

		lib = CDPLibrary(None)  # type: ignore[arg-type]  # builds one client per domain; no connection
		methods = {f'{d}.{m}' for d, c in vars(lib).items() if not d.startswith('_') for m in dir(c) if not m.startswith('_')}
	except Exception:  # cdp-use changed its layout: count nothing rather than anything
		methods = set()
	return frozenset(methods | {'BrowserUse.setCaptchaSolverEnabled', 'BrowserUse.getCaptchaSolverEnabled'})


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
			self.error_types[str(result.get('error_type') or 'unknown')[:MAX_NAME]] += 1
		self.imports.update(imported_modules(code))
		s = result.get('stats') or {}
		self.helpers.update({str(k)[:MAX_NAME]: n for k, n in (s.get('helpers') or {}).items()})
		for method, n in (s.get('cdp') or {}).items():  # the model can pass anything as the method: a URL, code
			self.cdp_methods[method if method in _cdp_methods() else 'invalid'] += int(n)
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
	if 'cdp_url' in clean:
		clean['cdp_url'] = cdp_category(clean['cdp_url'])  # a cloud browser's CDP hostname drives it
	clean['schema_version'] = 2
	return {**payload, 'properties': clean}
