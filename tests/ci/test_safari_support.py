"""Tests for Safari backend helpers."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

import pytest

from browser_use.browser.backends.base import BackendCapabilityReport
from browser_use.browser.backends.safari_backend import SafariRealProfileBackend, _run_jxa_sync
from browser_use.browser.safari.capabilities import SafariCapabilityReport, probe_safari_environment
from browser_use.browser.safari.profiles import SafariProfileStore
from browser_use.browser.session import BrowserSession
from browser_use.browser.views import BrowserError


def test_probe_safari_environment_reports_missing_socket(tmp_path: Path):
	"""Local probe should report unsupported when the host socket is missing."""
	socket_path = tmp_path / 'host.sock'

	with (
		patch('browser_use.browser.safari.capabilities.SAFARI_APP_PATH', tmp_path),
		patch('browser_use.browser.safari.capabilities._read_safari_version', return_value='26.3.1'),
		patch('browser_use.browser.safari.capabilities._read_macos_version', return_value='26.0'),
	):
		report = probe_safari_environment(socket_path)

	assert isinstance(report, SafariCapabilityReport)
	assert report.supported is False
	assert any('host socket' in issue.lower() for issue in report.issues)


def test_safari_profile_store_round_trip(tmp_path: Path):
	"""Safari profile bindings should persist to disk."""
	store_path = tmp_path / 'profiles.json'
	store = SafariProfileStore(store_path)

	store.bind('Personal', 'profile-personal', last_seen_target_id='tab-1234')
	store.bind('Work', 'profile-work')

	data = json.loads(store_path.read_text())
	assert len(data['bindings']) == 2
	assert store.get_identifier('Personal') == 'profile-personal'
	assert store.get_label('profile-work') == 'Work'


def test_browser_session_reports_safari_capabilities_without_start():
	"""Safari BrowserSession should expose local backend capabilities before startup."""
	report = BackendCapabilityReport(
		backend='safari',
		available=True,
		details={
			'safari_version': '26.3.1',
			'macos_version': '26.0',
			'gui_scripting_available': True,
			'screen_capture_available': True,
			'profile': 'Personal',
		},
	)
	session = BrowserSession(automation_backend='safari', safari_profile='Personal', headless=False)

	with patch('browser_use.browser.backends.safari_backend.probe_local_safari_backend', return_value=report):
		capabilities = session.get_backend_capabilities()

	assert capabilities.backend_name == 'safari'
	assert capabilities.browser_version == '26.3.1'
	assert capabilities.supported is True
	assert capabilities.supports_real_profile is True


def test_safari_guards_preserve_browser_session_docstrings():
	"""Safari-only guard clauses should not erase method docstrings."""
	get_cdp_doc = BrowserSession.get_or_create_cdp_session.__doc__
	client_for_node_doc = BrowserSession.cdp_client_for_node.__doc__

	assert get_cdp_doc is not None
	assert get_cdp_doc.lstrip().startswith('Get CDP session for a target')
	assert client_for_node_doc is not None
	assert client_for_node_doc.lstrip().startswith('Get CDP client for a specific DOM node')


def test_run_jxa_sync_wraps_timeout_as_browser_error():
	"""Timeouts from osascript should be normalized to BrowserError."""
	with patch(
		'browser_use.browser.backends.safari_backend.subprocess.run',
		side_effect=subprocess.TimeoutExpired(cmd=['osascript'], timeout=3, output='partial stdout', stderr='partial stderr'),
	):
		with pytest.raises(BrowserError, match='timed out') as exc_info:
			_run_jxa_sync('return 1;', timeout=3)

	assert exc_info.value.details == {
		'timeout_seconds': 3,
		'stderr': 'partial stderr',
		'stdout': 'partial stdout',
	}


@pytest.mark.asyncio
async def test_safari_take_screenshot_closes_mkstemp_fd(tmp_path: Path):
	"""Temporary screenshot descriptors should be closed immediately."""
	output_path = tmp_path / 'safari-shot.png'
	session = cast(BrowserSession, SimpleNamespace(logger=Mock()))
	backend = SafariRealProfileBackend(session)
	object.__setattr__(backend, '_ensure_profile_window', AsyncMock(return_value={'windowId': 123}))

	async def fake_to_thread(*args, **kwargs):
		output_path.write_bytes(b'png-bytes')
		return None

	with (
		patch('browser_use.browser.backends.safari_backend.tempfile.mkstemp', return_value=(99, str(output_path))),
		patch('browser_use.browser.backends.safari_backend.os.close') as close_fd,
		patch('browser_use.browser.backends.safari_backend.asyncio.to_thread', new=AsyncMock(side_effect=fake_to_thread)),
	):
		data = await backend.take_screenshot()

	assert data == b'png-bytes'
	close_fd.assert_called_once_with(99)
	assert not output_path.exists()


@pytest.mark.asyncio
async def test_safari_hover_element_uses_dom_mouse_events():
	"""Safari hover helper should synthesize hover events through page JavaScript."""
	session = cast(BrowserSession, SimpleNamespace(logger=Mock()))
	backend = SafariRealProfileBackend(session)
	object.__setattr__(backend, '_ensure_profile_window', AsyncMock(return_value={'windowId': 123}))
	evaluate_javascript = AsyncMock(return_value={'ok': True})
	object.__setattr__(backend, 'evaluate_javascript', evaluate_javascript)
	node = cast(Any, SimpleNamespace(backend_node_id=17))

	result = await backend.hover_element(node)

	assert result == {'ok': True}
	evaluate_javascript.assert_awaited_once()
	script = evaluate_javascript.await_args.args[0]
	assert 'pointerover' in script
	assert 'mousemove' in script
	assert 'data-browser-use-safari-id="17"' in script


@pytest.mark.asyncio
async def test_safari_double_click_element_uses_dom_double_click_events():
	"""Safari double-click helper should synthesize a dblclick sequence through page JavaScript."""
	session = cast(BrowserSession, SimpleNamespace(logger=Mock()))
	backend = SafariRealProfileBackend(session)
	object.__setattr__(backend, '_ensure_profile_window', AsyncMock(return_value={'windowId': 123}))
	refresh_focus_target = AsyncMock(return_value=None)
	evaluate_javascript = AsyncMock(return_value={'ok': True})
	object.__setattr__(backend, '_refresh_focus_target', refresh_focus_target)
	object.__setattr__(backend, 'evaluate_javascript', evaluate_javascript)
	node = cast(Any, SimpleNamespace(backend_node_id=23))

	result = await backend.double_click_element(node)

	assert result == {'ok': True}
	evaluate_javascript.assert_awaited_once()
	script = evaluate_javascript.await_args.args[0]
	assert 'dblclick' in script
	assert 'mousedown' in script
	assert 'data-browser-use-safari-id="23"' in script
	refresh_focus_target.assert_awaited_once()
