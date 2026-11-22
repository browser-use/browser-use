"""library_auth: where people without a Browser Use key stop, and whether they get one (views.AuthEvent). Enums, bools
and counts only: never the key, its id, the project, the login URL, state or code. A small file in telemetry_dir keeps
when this device first needed a key, how often, and whether its first keyed run was reported; only the numbers leave.
Off (ANONYMIZED_TELEMETRY=false, `browser-use telemetry disable`): no event, no file."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)
STATE = 'auth_state.json'
GATES = ('missing_key', 'key_rejected')  # the stages a device's gate counter counts
OUTCOME = {'login_succeeded': 'stored', 'login_cancelled': 'cancelled'}
_LOCK = threading.Lock()  # one read-modify-write of the file at a time in this process (counts across processes: about)
_UNSAVED: dict[str, dict] = {}  # path -> the state this process could not write there (a read-only HOME, Lambda)
_entry = ['agent']  # the program this process runs: agent (the library), cli (`browser-use`), mcp (its MCP server)


def set_entry(entry: str) -> None:
	"""The `browser-use` CLI and its MCP server name themselves: their events say entry cli / mcp, and their stderr stays
	their own (no telemetry notice)."""
	_entry[0] = entry


def capture(stage: str, method: str, automatic: bool, fields: dict[str, Any]) -> None:
	"""Queue one library_auth event (fields: key_gate, key_reason, outcome, entry). A gate also counts in the local file."""
	from browser_use.telemetry.service import telemetry

	if not telemetry().enabled:
		return
	state = _state(gate=stage in GATES)
	_send(stage, method, automatic, state, fields)


def keyed_success() -> None:
	"""A completed run that used a Browser Use key, on a device that needed one before: sent once per device."""
	try:
		from browser_use.telemetry.service import telemetry

		if not telemetry().enabled:
			return
		with _LOCK:
			state = _read()
			if not state.get('first_gate') or state.get('done'):
				return
			_save({**state, 'done': True})
		_send('keyed_success', '', False, state, {})
	except Exception as e:  # - telemetry never breaks a run
		logger.debug('library_auth: %s', e)


def key_source(llm: Any) -> str:
	"""Where a run's Browser Use key would come from: param (a gateway model's api_key=), env, login_oauth,
	login_device, login_manual (the stored key's source), or none. Read from the env and auth.json; never the key."""
	from browser_use.llm import gateway_alias

	if gateway_alias(llm) and getattr(llm, 'api_key', None):
		return 'param'
	if os.environ.get('BROWSER_USE_API_KEY', '').strip():
		return 'env'
	try:
		from browser_harness.auth import stored_auth_record

		record = stored_auth_record() or {}
	except Exception:  # - a corrupt or unreadable store holds no usable key
		return 'none'
	if not record.get('api_key'):
		return 'none'
	return {'manual': 'login_manual', 'device_code': 'login_device'}.get(str(record.get('source')), 'login_oauth')


def _send(stage: str, method: str, automatic: bool, state: dict, fields: dict) -> None:
	from browser_use.telemetry.service import telemetry
	from browser_use.telemetry.stats import is_internal
	from browser_use.telemetry.views import AuthEvent
	from browser_use.utils import get_browser_use_version

	first = state.get('first_gate')
	entry = fields.get('entry') or _entry[0]
	event = AuthEvent(
		get_browser_use_version(),
		stage,
		method,
		automatic,
		is_internal(),
		key_gate=fields.get('key_gate'),
		key_reason=fields.get('key_reason'),
		outcome=fields.get('outcome') or OUTCOME.get(stage),
		entry=entry,
		gate_count=int(state.get('gates') or 0),
		seconds_since_first_gate=max(0, int(time.time() - float(first))) if first else None,
	)
	if entry != 'agent':
		telemetry().notice = False  # the CLI's and the MCP server's stderr stay their own
	telemetry().capture(event)


def _path():
	from browser_use.telemetry.service import telemetry_dir

	return telemetry_dir() / STATE


def _state(gate: bool) -> dict:
	with _LOCK:
		state = _read()
		if gate:
			state = {**state, 'first_gate': state.get('first_gate') or time.time(), 'gates': int(state.get('gates') or 0) + 1}
			_save(state)
	return state


def _read() -> dict:
	path = _path()
	if str(path) in _UNSAVED:
		return dict(_UNSAVED[str(path)])
	try:
		state = json.loads(path.read_text(encoding='utf-8'))
	except (OSError, ValueError):
		state = {}
	return state if isinstance(state, dict) else {}


def _save(state: dict) -> None:
	"""Write the state; when the dir is unwritable, keep it for this process: the event is still sent and counted."""
	path = _path()
	try:
		_write(state)
		_UNSAVED.pop(str(path), None)
	except OSError as e:
		_UNSAVED[str(path)] = dict(state)
		logger.debug('library_auth: state not saved: %s', e)


def _write(state: dict) -> None:
	path = _path()
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_name(f'{STATE}.{os.getpid()}.{threading.get_ident()}.tmp')
	tmp.write_text(json.dumps(state), encoding='utf-8')
	os.replace(tmp, path)
