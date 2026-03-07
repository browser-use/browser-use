"""Tests for Safari backend helpers."""

import json
from pathlib import Path
from unittest.mock import patch

from browser_use.browser.backends.base import BackendCapabilityReport
from browser_use.browser.safari.capabilities import SafariCapabilityReport, probe_safari_environment
from browser_use.browser.safari.profiles import SafariProfileStore
from browser_use.browser.session import BrowserSession


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
