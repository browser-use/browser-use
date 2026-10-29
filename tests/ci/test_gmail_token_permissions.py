"""The Gmail OAuth token file must not be readable by other local users.

`gmail_token.json` stores a long-lived `refresh_token` and the OAuth client's
`client_secret` (see `google.oauth2.credentials.Credentials.to_json`), so a
default-umask write would leave a live Gmail credential at mode 0644.
"""

import io
import os
import stat
import sys
from pathlib import Path

import pytest

from browser_use.integrations.gmail.service import _write_secret_file

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX file modes')


def _mode(path: Path) -> int:
	return path.stat().st_mode & 0o777


async def test_secret_file_is_owner_only(tmp_path: Path):
	"""A newly created token file is 0600, not the 0644 the default umask gives."""
	token = tmp_path / 'gmail_token.json'
	await _write_secret_file(token, '{"refresh_token": "x", "client_secret": "y"}')

	assert _mode(token) == 0o600
	assert not _mode(token) & stat.S_IROTH, 'token file is world-readable'
	assert not _mode(token) & stat.S_IRGRP, 'token file is group-readable'
	assert token.read_text() == '{"refresh_token": "x", "client_secret": "y"}'


async def test_existing_world_readable_file_is_corrected(tmp_path: Path):
	"""A token left at 0644 by an older version is tightened on the next write."""
	token = tmp_path / 'gmail_token.json'
	token.write_text('{"refresh_token": "old"}')
	os.chmod(token, 0o644)
	assert _mode(token) == 0o644

	await _write_secret_file(token, '{"refresh_token": "new"}')

	assert _mode(token) == 0o600
	assert token.read_text() == '{"refresh_token": "new"}'


async def test_write_is_truncating(tmp_path: Path):
	"""A shorter payload must not leave a tail of the previous credential behind."""
	token = tmp_path / 'gmail_token.json'
	await _write_secret_file(token, 'a' * 200)
	await _write_secret_file(token, 'b')

	assert token.read_text() == 'b'


async def test_mode_failure_does_not_write_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
	"""If the mode cannot be tightened, the new credential is not written and the old file is left intact."""
	token = tmp_path / 'gmail_token.json'
	token.write_text('{"refresh_token": "old"}')
	os.chmod(token, 0o644)

	def refuse(fd: int, mode: int) -> None:
		raise PermissionError('fchmod not permitted')

	monkeypatch.setattr(os, 'fchmod', refuse)
	with pytest.raises(PermissionError):
		await _write_secret_file(token, '{"refresh_token": "new"}')

	assert token.read_text() == '{"refresh_token": "old"}'


async def test_secret_is_not_written_by_reopening_the_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
	"""The payload goes through the 0600 descriptor; reopening the token path by name would
	let a file recreated in between receive the secret at the default umask."""
	token = tmp_path / 'gmail_token.json'
	real_io_open = io.open

	def guarded_open(file, *args, **kwargs):
		if not isinstance(file, int) and Path(file) == token:
			raise AssertionError('token file reopened by path')
		return real_io_open(file, *args, **kwargs)

	monkeypatch.setattr(io, 'open', guarded_open)
	await _write_secret_file(token, 'secret')
	monkeypatch.undo()

	assert _mode(token) == 0o600
	assert token.read_text() == 'secret'
