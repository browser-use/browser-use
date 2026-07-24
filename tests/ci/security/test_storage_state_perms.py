"""Tests for storage_state.json (session cookie) file permissions.

StorageStateWatchdog persists authenticated session cookies + localStorage to
storage_state.json. Under the default umask that file is world-readable (0o644),
and the 30s autosave silently re-downgrades a user-pre-created 0o600 file on
every write, so on a multi-user host a co-tenant can read live session cookies.
The fix writes via tempfile.mkstemp (O_EXCL + 0o600 from creation) and restricts
the .json.bak backup before its rename, mirroring the project's own
credential-file posture (skill_cli/config.py write_config, sync/auth.py, the
daemon Unix socket).
"""

from __future__ import annotations

import json
import logging
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from browser_use.browser.watchdogs.storage_state_watchdog import StorageStateWatchdog

skip_on_windows = pytest.mark.skipif(
	sys.platform == 'win32',
	reason='POSIX file-mode bits are not meaningful on Windows.',
)

_FAKE_STATE = {
	'cookies': [{'name': 'session', 'value': 'secret-token', 'domain': 'example.com', 'path': '/'}],
	'origins': [{'origin': 'https://example.com', 'localStorage': [{'name': 'k', 'value': 'v'}]}],
}


def _make_watchdog() -> StorageStateWatchdog:
	"""Build a watchdog without a real browser via pydantic model_construct.

	_save_storage_state only touches browser_session.get_or_create_cdp_session,
	browser_session._cdp_get_storage_state, browser_session.logger and
	event_bus.dispatch — all stubbed below.
	"""

	async def _get_or_create_cdp_session(target_id=None):
		return True

	async def _cdp_get_storage_state():
		return json.loads(json.dumps(_FAKE_STATE))  # deep copy

	browser_session = SimpleNamespace(
		get_or_create_cdp_session=_get_or_create_cdp_session,
		_cdp_get_storage_state=_cdp_get_storage_state,
		logger=logging.getLogger('test-storage-state-perms'),
	)
	event_bus = SimpleNamespace(dispatch=lambda *a, **k: None)
	return StorageStateWatchdog.model_construct(browser_session=browser_session, event_bus=event_bus)


def _mode(path: Path) -> int:
	return stat.S_IMODE(os.stat(path).st_mode)


@skip_on_windows
async def test_storage_state_written_0o600(tmp_path: Path) -> None:
	"""A freshly written storage_state.json must be 0o600 (owner-only)."""
	path = tmp_path / 'storage_state.json'

	await _make_watchdog()._save_storage_state(path=str(path))

	assert path.exists()
	mode = _mode(path)
	assert mode == 0o600, (
		f'storage_state.json has mode {oct(mode)}, expected 0o600. Session cookies '
		f'must not be world/group readable on multi-user hosts.'
	)
	# Sanity: we really are guarding a live secret.
	assert 'secret-token' in path.read_text()


@skip_on_windows
async def test_storage_state_autosave_does_not_redowngrade(tmp_path: Path) -> None:
	"""A pre-existing 0o644 file (and its .json.bak backup) end up 0o600 after save."""
	path = tmp_path / 'storage_state.json'
	# Simulate a stale world-readable file (external creation, or pre-fix autosave).
	path.write_text(json.dumps({'cookies': [], 'origins': []}))
	path.chmod(0o644)
	assert _mode(path) == 0o644

	await _make_watchdog()._save_storage_state(path=str(path))

	assert _mode(path) == 0o600, 'autosave must not leave storage_state.json world-readable'
	# The backup holds the previous cookie state, so it must be locked down too.
	backup = path.with_suffix('.json.bak')
	assert backup.exists()
	assert _mode(backup) == 0o600, f'{backup.name} (contains cookies) must be 0o600, got {oct(_mode(backup))}'


@skip_on_windows
async def test_pre_existing_insecure_backup_locked_down_even_when_save_fails(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""A 0o644 .json.bak left by a pre-fix version is restricted even if the save aborts."""
	import pathlib

	path = tmp_path / 'storage_state.json'
	path.write_text(json.dumps({'cookies': [], 'origins': []}))
	path.chmod(0o644)
	backup = path.with_suffix('.json.bak')
	backup.write_text(json.dumps({'cookies': [{'name': 'old', 'value': 'leak', 'domain': 'x', 'path': '/'}]}))
	backup.chmod(0o644)

	# Force the json -> .json.bak rename to fail, after the pre-rename chmods run.
	real_replace = pathlib.Path.replace

	def boom(self, target):
		if str(target).endswith('.json.bak'):
			raise OSError('forced backup-rename failure')
		return real_replace(self, target)

	monkeypatch.setattr(pathlib.Path, 'replace', boom)

	# _save_storage_state swallows + logs the error, so this returns rather than raises.
	await _make_watchdog()._save_storage_state(path=str(path))

	# Despite the failed save, neither cookie-bearing file is left world-readable.
	assert _mode(backup) == 0o600, f'pre-existing backup must be locked down, got {oct(_mode(backup))}'
	assert _mode(path) == 0o600, f'current file must be locked down, got {oct(_mode(path))}'


@skip_on_windows
async def test_stale_backup_locked_down_when_current_file_missing(tmp_path: Path) -> None:
	"""A lone stale 0o644 .json.bak (current file absent) is restricted on the next save."""
	path = tmp_path / 'storage_state.json'  # intentionally does not exist
	backup = path.with_suffix('.json.bak')
	backup.write_text(json.dumps({'cookies': [{'name': 'old', 'value': 'leak', 'domain': 'x', 'path': '/'}]}))
	backup.chmod(0o644)

	await _make_watchdog()._save_storage_state(path=str(path))

	assert path.exists() and _mode(path) == 0o600
	assert _mode(backup) == 0o600, f'stale backup must be locked down even with no current file, got {oct(_mode(backup))}'
