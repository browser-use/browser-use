"""Tests for doctor command."""

import pytest

from browser_use.skill_cli.commands import doctor


@pytest.mark.asyncio
async def test_doctor_handle_returns_valid_structure():
	"""Test that doctor.handle() returns a valid result structure."""
	result = await doctor.handle()

	# Verify structure
	assert 'status' in result
	assert result['status'] in ('healthy', 'issues_found')
	assert 'checks' in result
	assert 'summary' in result

	# Verify all expected checks are present
	expected_checks = ['package', 'browser', 'api_key', 'cloudflared', 'network']
	for check in expected_checks:
		assert check in result['checks']
		assert 'status' in result['checks'][check]
		assert 'message' in result['checks'][check]


def test_check_package_installed():
	"""Test _check_package returns ok when browser-use is installed."""
	# browser-use is always installed in the test environment
	result = doctor._check_package()
	assert result['status'] == 'ok'
	assert 'browser-use' in result['message']


def test_check_browser_returns_valid_structure():
	"""Test _check_browser returns a valid result."""
	result = doctor._check_browser()
	assert 'status' in result
	assert result['status'] in ('ok', 'warning')
	assert 'message' in result


def test_check_api_key_with_env_var(monkeypatch):
	"""Test _check_api_key_config when API key is set via env var."""
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'test_key_12345')

	result = doctor._check_api_key_config()
	assert result['status'] == 'ok'
	assert 'configured' in result['message'].lower()


def test_check_api_key_missing(monkeypatch):
	"""Test _check_api_key_config when API key is not available."""
	# Remove env var if set
	monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)

	# Also need to ensure no config file provides a key
	# by temporarily setting XDG_CONFIG_HOME to empty temp dir
	import tempfile

	with tempfile.TemporaryDirectory() as tmpdir:
		monkeypatch.setenv('XDG_CONFIG_HOME', tmpdir)
		# On macOS, also need to handle ~/Library/Application Support
		monkeypatch.setenv('HOME', tmpdir)

		# Clear any cached config
		from browser_use.skill_cli import api_key

		if hasattr(api_key, '_cached_key'):
			monkeypatch.setattr(api_key, '_cached_key', None)

		result = doctor._check_api_key_config()
		assert result['status'] == 'missing'
		assert 'no api key' in result['message'].lower()


def test_check_cloudflared_returns_valid_structure():
	"""Test _check_cloudflared returns a valid result structure."""
	result = doctor._check_cloudflared()

	assert 'status' in result
	assert result['status'] in ('ok', 'missing')
	assert 'message' in result

	# If available, should have details
	if result['status'] == 'ok':
		assert 'available' in result['message'].lower() or 'cloudflared' in result['message'].lower()


@pytest.mark.asyncio
async def test_check_network_returns_valid_structure():
	"""Test _check_network returns a valid result structure."""
	result = await doctor._check_network()

	assert 'status' in result
	assert result['status'] in ('ok', 'warning')
	assert 'message' in result


def test_summarize_checks_all_ok():
	"""Test _summarize_checks when all checks pass."""
	checks = {
		'check1': {'status': 'ok'},
		'check2': {'status': 'ok'},
		'check3': {'status': 'ok'},
	}
	summary = doctor._summarize_checks(checks)
	assert '3/3' in summary


def test_summarize_checks_mixed():
	"""Test _summarize_checks with mixed results."""
	checks = {
		'check1': {'status': 'ok'},
		'check2': {'status': 'warning'},
		'check3': {'status': 'missing'},
	}
	summary = doctor._summarize_checks(checks)
	assert '1/3' in summary
	assert '1 warning' in summary
	assert '1 missing' in summary


def test_summarize_checks_with_errors():
	"""Test _summarize_checks with errors."""
	checks = {
		'check1': {'status': 'ok'},
		'check2': {'status': 'error'},
	}
	summary = doctor._summarize_checks(checks)
	assert '1/2' in summary
	assert '1 error' in summary
