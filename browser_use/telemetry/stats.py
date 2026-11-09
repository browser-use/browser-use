"""What a run reports to telemetry: counts, names, hostnames and classes. Never text that the task, the model, a page or
an exception wrote (TELEMETRY.md). Names the model's code can choose (imported modules, exception classes, cdp()
methods) are kept only when Python, an installed package or the CDP protocol defines them."""

from __future__ import annotations

import ast
import ipaddress
import os
import platform
import re
import sys
import warnings
from collections import Counter
from dataclasses import dataclass, field
from functools import cache
from importlib.metadata import PackageNotFoundError, packages_distributions, version
from pathlib import PurePath
from typing import Any

from browser_use.domains import parse_url

MAX_KEYS = 50  # per map or list: a run that visits 10k hosts sends the 50 most frequent
MAX_NAME = 64  # characters per name
CLI_CONTENT = ('task', 'output', 'steps', 'error_message')  # browser-harness cli_event fields that carry text


HOSTNAME = re.compile(r'(?:[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?\.)*[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?')
HOST_SCHEMES = ('http', 'https', 'ws', 'wss')
# a download's extension is sent when it is one of these, else 'other': the rest of a file name is the site's text
DOWNLOAD_EXTS = frozenset(
	'pdf csv tsv txt json xml html htm md rtf doc docx odt xls xlsx xlsm ods ppt pptx odp key numbers pages epub ics vcf '
	'eml msg zip gz tgz tar bz2 xz 7z rar dmg pkg exe msi deb rpm apk iso bin png jpg jpeg gif webp svg bmp tif tiff ico '
	'heic avif psd mp3 wav ogg m4a flac mp4 mov webm avi mkv js css py ipynb sql log yaml yml toml parquet ofx qfx qif '
	'torrent ttf otf woff woff2 pem crt'.split()
)


def host(url: Any) -> str | None:
	"""The hostname of an http(s) or ws(s) URL as the browser reads it (lowercase, punycode, IPs as addresses), without
	user, password, port, path, query or fragment. None without one, and None when it is not a DNS name or an IP:
	urlsplit() returns any text between // and the next / ('https://the task as text/') as the hostname."""
	try:
		u = parse_url(str(url))
	except Exception:  # - a host idna cannot read: no host
		return None
	if u is None or u.scheme not in HOST_SCHEMES or not u.host:
		return None
	try:
		ipaddress.ip_address(u.host)
		return u.host
	except ValueError:
		return u.host if len(u.host) <= 253 and HOSTNAME.fullmatch(u.host) else None


def download_ext(path: Any) -> str:
	"""A downloaded file's extension, lowercased, when it is a common file type; 'other' for any other, 'none'."""
	ext = PurePath(str(path)).suffix.lower().lstrip('.')
	return ext if ext in DOWNLOAD_EXTS else 'other' if ext else 'none'


def model_id(name: Any) -> str:
	"""The model id as passed, except a local path (vLLM, llama.cpp serve a model by its path): its last segment,
	without the directories (a user name). 'other' for a URL."""
	text = str(name or '')
	if '://' in text:
		return 'other'
	if text.startswith(('/', '~', '.')) or '\\' in text or re.match(r'[A-Za-z]:[\\/]', text):
		text = re.split(r'[\\/]', text.rstrip('/\\'))[-1]
	return text[:MAX_NAME]


def provider_name(provider: Any) -> str:
	"""A provider's name: a Pydantic AI Provider object's repr holds its base_url (an account or tenant in the URL)."""
	if isinstance(provider, str):
		return provider[:MAX_NAME]
	name = getattr(provider, 'name', None)
	return name[:MAX_NAME] if isinstance(name, str) else 'other'


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


def known_module(name: str) -> bool:
	"""In the standard library, browser-use or an installed distribution. The stdlib check comes first: listing the
	installed distributions takes ~130 ms the first time in a process."""
	return name in sys.stdlib_module_names or name == 'browser_use' or name in _known_modules()


def imported_modules(code: str) -> list[str]:
	"""Top-level modules a cell imports ('pandas' for `from pandas.io import x`); 'other' for one that is neither in
	the standard library nor installed (a module the model wrote can have any name). Nothing else of the code."""
	try:
		with warnings.catch_warnings():  # the worker already showed the model its SyntaxWarnings; not the user's stderr
			warnings.simplefilter('ignore')
			tree = ast.parse(code)
	except (SyntaxError, ValueError):
		return []
	names: list[str] = []
	for node in ast.walk(tree):
		if isinstance(node, ast.Import):
			names += [a.name.split('.')[0] for a in node.names]
		elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
			names.append(node.module.split('.')[0])
	return [n if known_module(n) else 'other' for n in names]


def error_class(e: BaseException | type) -> str:
	"""The exception's (or class's) name when Python, the standard library or an installed package defines it; 'custom'
	for a class the model's code defined, which could be named anything."""
	cls = e if isinstance(e, type) else type(e)
	module = sys.modules.get(cls.__module__ or '')
	# Pydantic AI raises classes it combines at runtime (ModelServerError + ModelHTTPError, named ModelServerError):
	# the module's class of that name is one of its bases
	known = known_module((cls.__module__ or '').split('.')[0]) and getattr(module, cls.__name__, None) in cls.__mro__
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


def fold(into: dict[str, list[int]], timings: dict) -> None:
	"""Adds one cell's [calls, errors, ns total, ns max] per name into a run's."""
	for name, (calls, errors, total, peak) in timings.items():
		s = into.get(name)
		if s is None:
			into[name] = [calls, errors, total, peak]
		else:
			s[0] += calls
			s[1] += errors
			s[2] += total
			s[3] = max(s[3], peak)


@dataclass
class RunStats:
	"""Counters for one Agent.run(), filled from each REPL cell's result (worker.py `stats`). add_cell runs on the agent
	path, so it only appends and adds; names the model's code chooses (imports, cdp() methods) are checked when read,
	in the telemetry thread (that check lists the installed packages and CDP methods: ~300 ms the first time)."""

	cells: int = 0
	cell_errors: int = 0
	cell_seconds: float = 0.0
	images: int = 0
	navigations: int = 0
	helpers: Counter = field(default_factory=Counter)  # helper name -> calls, e.g. goto_url, bu.click
	domains: Counter = field(default_factory=Counter)  # hostname -> cells that saw it
	error_types: Counter = field(default_factory=Counter)  # exception class of each failed cell
	events: Counter = field(default_factory=Counter)  # captcha_started, captcha_solved, captcha_failed, download_started
	helper_t: dict[str, list[int]] = field(default_factory=dict)  # helper -> [calls, errors, ns total, ns max]
	cdp_t: dict[str, list[int]] = field(default_factory=dict)  # every CDP method the worker sent, unchecked, same shape
	codes: list[str] = field(default_factory=list)  # cell code, parsed for imports when read; never sent
	cdp_raw: Counter = field(default_factory=Counter)  # the agent's own cdp() calls by method, unchecked

	def add_cell(self, result: dict, code: str, seconds: float) -> None:
		self.cells += 1
		self.cell_seconds += seconds
		self.images += len(result.get('images') or [])
		if result.get('error'):
			self.cell_errors += 1
			self.error_types[str(result.get('error_type') or 'unknown')[:MAX_NAME]] += 1
		self.codes.append(code)
		s = result.get('stats') or {}
		self.helpers.update({str(k)[:MAX_NAME]: n for k, n in (s.get('helpers') or {}).items()})
		self.cdp_raw.update(s.get('cdp') or {})
		fold(self.helper_t, s.get('helper_t') or {})
		fold(self.cdp_t, s.get('cdp_t') or {})
		self.domains.update(s.get('hosts') or [])
		self.events.update(s.get('events') or {})
		self.navigations += int(s.get('navigations') or 0)

	@property
	def imports(self) -> Counter:
		"""Top-level modules cells imported ('other' for one neither in the standard library nor installed)."""
		return Counter(m for code in self.codes for m in imported_modules(code))

	@property
	def cdp_methods(self) -> Counter:
		"""The agent's cdp() calls by method; anything that is not a CDP protocol method counts as 'invalid'."""
		return checked_methods(self.cdp_raw)

	def cdp_stats(self) -> dict[str, list[int]]:
		"""Every CDP method the worker sent: [calls, errors, ns total, ns max], unknown names folded into 'invalid'."""
		out: dict[str, list[int]] = {}
		for method, s in self.cdp_t.items():
			fold(out, {method if method in _cdp_methods() else 'invalid': s})
		return out


def checked_methods(counts: Counter) -> Counter:
	out: Counter = Counter()
	for method, n in counts.items():  # the model can pass anything as the method: a URL, code
		out[method if method in _cdp_methods() else 'invalid'] += int(n)
	return out


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
