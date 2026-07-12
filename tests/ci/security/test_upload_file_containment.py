"""Tests for upload_file FileSystem path containment (GHSA-j9hj-92j8-jv9h).

The `upload_file` action used to construct the absolute upload path by joining
`file_system.get_dir()` with the agent-controlled `params.path`. Because
`FileSystem.get_file()` matches by basename (it does `os.path.basename` first),
an agent-controlled path like `../note.md` would:

1. Pass `get_file()` lookup if a file named `note.md` exists in the FileSystem.
2. Be naively joined to `data_dir` producing `data_dir/../note.md`, which
   resolves *outside* the FileSystem directory.
3. Be uploaded to the browser as the resolved escaped file.

The fix uses `file_obj.full_name` (the FileSystem-owned basename) for the join
and additionally verifies via `os.path.realpath` that the result is contained
in `data_dir`.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from browser_use.agent.views import ActionResult
from browser_use.filesystem.file_system import FileSystem
from browser_use.tools.service import Tools


class _StubBrowserSession:
	"""Minimal stub exposing only the attributes `upload_file` touches before it
	would hand off to CDP. We stop the action just after path resolution.

	Per the project rule "use real objects", this stub stands in only for the
	browser/CDP boundary that has no bearing on the security property under test
	(file path containment); the FileSystem and Tools registry are real.
	"""

	is_local = True
	downloaded_files: list[str] = []
	agent_focus_target_id: str | None = None
	session_manager: Any = None
	cdp_client: Any = None

	# Capture the params.path passed in by the action so the test can inspect it.
	captured_resolved_path: str | None = None

	async def get_current_page_url(self) -> str:
		return 'about:blank'

	async def get_selector_map(self) -> dict:
		# Returning an empty map causes upload_file to bail with an
		# "Element ... does not exist" error AFTER it has resolved the path.
		return {}


@pytest.fixture
def stub_session() -> _StubBrowserSession:
	return _StubBrowserSession()


async def test_traversal_in_agent_path_does_not_escape_filesystem_dir(
	tmp_path,
	stub_session: _StubBrowserSession,
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""GHSA-j9hj-92j8-jv9h: agent-controlled `../note.md` must not cause
	the upload path to escape `file_system.get_dir()`."""
	fs = FileSystem(base_dir=tmp_path)
	# Legitimate FileSystem-owned file.
	await fs.write_file('note.md', 'safe content')
	data_dir_real = os.path.realpath(str(fs.get_dir()))

	# Capture every path that the action checks for existence — the first one
	# is the resolved upload path. Pre-fix this is the escape; post-fix it must
	# be the inside path.
	exists_calls: list[str] = []
	real_exists = os.path.exists

	def capturing_exists(path: str) -> bool:
		exists_calls.append(str(path))
		return real_exists(path)

	monkeypatch.setattr('browser_use.tools.service.os.path.exists', capturing_exists)

	tools = Tools()
	result = await tools.registry.execute_action(
		'upload_file',
		{'index': 0, 'path': '../note.md'},
		browser_session=stub_session,  # type: ignore[arg-type]
		file_system=fs,
		available_file_paths=[],
	)

	# Whatever the eventual ActionResult, the first os.path.exists call inside
	# upload_file is on the resolved upload path. It MUST be contained in data_dir.
	assert exists_calls, 'upload_file should call os.path.exists on the resolved path'
	resolved = os.path.realpath(exists_calls[0])
	assert resolved == data_dir_real or resolved.startswith(data_dir_real + os.sep), (
		f'Upload path escaped FileSystem directory.\n'
		f'  data_dir : {data_dir_real}\n'
		f'  resolved : {resolved}\n'
		f'  raw      : {exists_calls[0]}'
	)

	# Sanity: the resolved path should point at the FileSystem-owned file.
	assert resolved == os.path.realpath(str(fs.get_dir() / 'note.md'))

	# The action itself will fail with an "Element does not exist" error from
	# the stub selector map — that's fine; we're only checking the path.
	assert isinstance(result, ActionResult)


async def test_traversal_with_no_basename_match_still_fails_safely(
	tmp_path,
	stub_session: _StubBrowserSession,
) -> None:
	"""Sanity: if the basename does not match any FileSystem-owned file, the
	action must reject with an availability error — never reach the join sink."""
	fs = FileSystem(base_dir=tmp_path)
	# Note: no `note.md` registered in the FileSystem.

	tools = Tools()
	result = await tools.registry.execute_action(
		'upload_file',
		{'index': 0, 'path': '../note.md'},
		browser_session=stub_session,  # type: ignore[arg-type]
		file_system=fs,
		available_file_paths=[],
	)

	assert isinstance(result, ActionResult)
	assert result.error is not None
	# Should be the "not available" rejection, not a path-resolution success.
	assert 'not available' in result.error.lower() or 'does not exist' in result.error.lower()


class _StubRemoteBrowserSession(_StubBrowserSession):
	"""Stub for a remote (non-local) browser session — the upload action's
	rules differ here. Remote paths are passed through to the browser process."""

	is_local = False


async def test_remote_session_does_not_rewrite_to_local_filesystem_on_basename_collision(
	tmp_path,
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""For remote sessions, an absolute remote path that happens to share a
	basename with a local FileSystem-managed file MUST be passed through
	unchanged. Rewriting to the local FileSystem path would silently upload
	the wrong file (the local managed one) instead of the remote-machine file
	the agent referenced.

	Pre-existing issue surfaced by the GHSA-j9hj-92j8-jv9h review (codex bot).
	"""
	fs = FileSystem(base_dir=tmp_path)
	# Create a local managed file with a basename that collides with the
	# remote path the agent will reference.
	await fs.write_file('note.md', 'LOCAL content the agent did NOT ask for')

	# What the remote-session agent would pass — a path valid on the remote
	# machine, NOT in the local FileSystem.
	remote_path = '/tmp/note.md'

	# Capture every path that the action checks for existence. For remote
	# sessions the local-existence check is skipped, so we instead capture
	# the resolved path via the same os.path.exists hook used by the local
	# test — if the rewrite-to-local-filesystem branch fires, the next call
	# will be against the data_dir path; if not, no call should reference it.
	exists_calls: list[str] = []
	real_exists = os.path.exists

	def capturing_exists(path: str) -> bool:
		exists_calls.append(str(path))
		return real_exists(path)

	monkeypatch.setattr('browser_use.tools.service.os.path.exists', capturing_exists)

	tools = Tools()
	await tools.registry.execute_action(
		'upload_file',
		{'index': 0, 'path': remote_path},
		browser_session=_StubRemoteBrowserSession(),  # type: ignore[arg-type]
		file_system=fs,
		available_file_paths=[],
	)

	# The action should NOT have rewritten to a local FileSystem path. If it
	# had, we'd see the data_dir/note.md path appear in the captured calls.
	data_dir_str = str(fs.get_dir())
	rewrites = [p for p in exists_calls if p.startswith(data_dir_str)]
	assert not rewrites, (
		f'Remote session upload silently rewrote to local FileSystem path: {rewrites}. '
		f'The agent intended to upload {remote_path!r}; the rewrite would have uploaded the local managed file instead.'
	)
