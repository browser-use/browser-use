"""Tunable agent defaults (knobs) that an experiment can set, and the values a run used (TELEMETRY.md "Flags").

Only typed numbers, clamped to a range. Never strings, prompts, domains, secrets, URLs or telemetry settings: the model
writes and runs code in logged-in browsers, so a remote string would be a remote control channel.

Per knob: env BROWSER_USE_FLAG_<NAME> wins, then a remotely assigned value, then the code default. Values are resolved
when a run starts and never change during it. Remote values come from PostHog feature flags named bu1-<knob>, fetched
by the telemetry thread at most once per 24 h and cached in <config dir>/flags.json; a run only reads that cache and
never waits on the network. Remote fetching is off unless BROWSER_USE_REMOTE_FLAGS is true (REMOTE below); with
ANONYMIZED_TELEMETRY=false nothing is fetched, read or written, and env overrides still apply.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from browser_use.config import CONFIG

REMOTE = False  # default for BROWSER_USE_REMOTE_FLAGS; turned on in the release that ships the first experiment
TTL_S = 24 * 3600
FETCH_TIMEOUT_S = 1.5
PREFIX = 'bu1-'
# name: (type, default, min, max). A None default means the code computes it (compact_at_tokens: from the model's window).
KNOBS: dict[str, tuple[type, Any, float, float]] = {
	'keep_image_results': (int, 2, 1, 6),
	'cell_timeout_s': (float, 120.0, 30, 300),
	'compact_at_tokens': (int, None, 50_000, 400_000),
	'client_compact_frac': (float, 0.75, 0.5, 0.9),
	'delivery_frac': (float, 0.9, 0.8, 0.97),
	'model_timeout_s': (float, 300.0, 120, 900),
}
_cache: dict[str, Any] | None = None  # flags.json, read once per process; the telemetry thread replaces it after a fetch


def parse(name: str, raw: Any) -> Any:
	"""raw as the knob's type, clamped to its range; None when it does not parse."""
	kind, _, lo, hi = KNOBS[name]
	try:
		if isinstance(raw, bool) or raw is None:
			return None
		value = kind(float(raw)) if kind is int else kind(raw)
	except (TypeError, ValueError, OverflowError):
		return None
	if value != value:  # NaN
		return None
	return min(max(value, kind(lo)), kind(hi))


def remote_enabled() -> bool:
	if not CONFIG.ANONYMIZED_TELEMETRY:
		return False
	value = os.getenv('BROWSER_USE_REMOTE_FLAGS', '').strip().lower()
	return value[0] in 'ty1' if value else REMOTE


def path():
	return CONFIG.BROWSER_USE_CONFIG_DIR / 'flags.json'


def cached() -> dict[str, Any]:
	"""{'fetched': unix time of the last attempt, 'flags': {flag key: raw value}}; {} when there is none."""
	global _cache
	if _cache is None:
		try:
			_cache = json.loads(path().read_text(encoding='utf-8'))
			if not isinstance(_cache, dict):
				_cache = {}
		except (OSError, ValueError):
			_cache = {}
	return _cache


def resolve() -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
	"""(values, sources, remote assignments) for a run. sources: d default, e env, r remote. Remote assignments are
	{flag key: raw value} for $feature/<key>. Reads the env and the in-memory cache only."""
	remote = (cached().get('flags') or {}) if remote_enabled() else {}
	values: dict[str, Any] = {}
	sources: dict[str, str] = {}
	assigned: dict[str, str] = {}
	for name, (_, default, _, _) in KNOBS.items():
		env = os.getenv(f'BROWSER_USE_FLAG_{name.upper()}')
		key = PREFIX + name.replace('_', '-')
		if env is not None and (value := parse(name, env)) is not None:
			values[name], sources[name] = value, 'e'
		elif key in remote and (value := parse(name, remote[key])) is not None:
			values[name], sources[name] = value, 'r'
			assigned[key] = str(remote[key])[:32]
		else:
			values[name], sources[name] = default, 'd'
	return values, sources, assigned


def refresh(host: str, api_key: str, distinct_id: str) -> None:
	"""Fetch bu1-* flags when the cache is older than TTL_S (the telemetry thread calls this). The attempt time is saved
	even when the fetch fails, so a failing fetch is not repeated within TTL_S. Never raises."""
	global _cache
	if not remote_enabled() or time.time() - float(cached().get('fetched') or 0) < TTL_S:
		return
	import urllib.request

	flags: dict[str, Any] = dict(cached().get('flags') or {})
	try:
		body = json.dumps({'api_key': api_key, 'distinct_id': distinct_id}).encode()
		request = urllib.request.Request(f'{host}/flags?v=2', body, {'Content-Type': 'application/json'})
		with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_S) as r:
			answer = json.loads(r.read())
		flags = {}
		for key, flag in (answer.get('flags') or {}).items():
			if not (isinstance(key, str) and key.startswith(PREFIX) and isinstance(flag, dict) and flag.get('enabled')):
				continue
			payload = (flag.get('metadata') or {}).get('payload')
			flags[key] = json.loads(payload) if isinstance(payload, str) and payload.strip() else flag.get('variant')
	except Exception:  # - offline, blocked, a changed API: keep the last values
		pass
	_cache = {'fetched': time.time(), 'flags': flags}
	try:
		tmp = path().with_suffix(f'.{os.getpid()}.tmp')
		tmp.write_text(json.dumps(_cache), encoding='utf-8')
		os.replace(tmp, path())
	except OSError:
		pass
