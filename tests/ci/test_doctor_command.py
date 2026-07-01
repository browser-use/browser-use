"""Tests for doctor command."""

from browser_use.skill_cli.commands import doctor


async def test_doctor_handle_returns_valid_structure():
	"""Test that doctor.handle() returns a valid result structure."""
	result = await doctor.handle()

	# Verify structure
	assert 'status' in result
	assert result['status'] in ('healthy', 'issues_found')
	assert 'checks' in result
	assert 'summary' in result

	# Verify all expected checks are present
	expected_checks = ['package', 'browser', 'network', 'extensions', 'cloudflared', 'profile_use']
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


def test_check_extensions_returns_valid_structure(tmp_path, monkeypatch):
	"""Test _check_extensions returns diagnostic details."""
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path / 'browseruse'))
	monkeypatch.delenv('BROWSER_USE_DISABLE_EXTENSIONS', raising=False)

	result = doctor._check_extensions()

	assert result['status'] in ('ok', 'warning')
	assert 'message' in result
	assert 'details' in result
	assert result['details']['enabled'] is True
	assert result['details']['cache_dir'].endswith('extensions')
	assert 'unpacked_count' in result['details']
	assert 'BROWSER_USE_DISABLE_EXTENSIONS=unset' in result['note']


def test_check_extensions_reports_disabled_env_var(tmp_path, monkeypatch):
	"""Test _check_extensions reports when default extensions are disabled by env."""
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path / 'browseruse'))
	monkeypatch.setenv('BROWSER_USE_DISABLE_EXTENSIONS', '1')

	result = doctor._check_extensions()

	assert result['status'] == 'warning'
	assert result['details']['enabled'] is False
	assert result['details']['env'] == '1'
	assert 'BROWSER_USE_DISABLE_EXTENSIONS' in result['message']
	assert 'BROWSER_USE_DISABLE_EXTENSIONS=1' in result['note']


def test_check_extensions_reports_cached_manifest(tmp_path, monkeypatch):
	"""Test _check_extensions reports cached unpacked MV3 extensions."""
	config_dir = tmp_path / 'browseruse'
	extension_dir = config_dir / 'extensions' / 'extension-id'
	extension_dir.mkdir(parents=True)
	(extension_dir / 'manifest.json').write_text('{"manifest_version": 3}', encoding='utf-8')

	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(config_dir))
	monkeypatch.delenv('BROWSER_USE_DISABLE_EXTENSIONS', raising=False)

	result = doctor._check_extensions()

	assert result['status'] == 'ok'
	assert result['details']['unpacked_count'] == 1
	assert result['details']['unpacked_extension_ids'] == ['extension-id']


async def test_check_network_returns_valid_structure():
	"""Test _check_network returns a valid result structure."""
	result = await doctor._check_network()

	assert 'status' in result
	assert result['status'] in ('ok', 'warning')
	assert 'message' in result


def test_check_cloudflared_returns_valid_structure():
	"""Test _check_cloudflared returns a valid result."""
	result = doctor._check_cloudflared()
	assert 'status' in result
	assert result['status'] in ('ok', 'missing')
	assert 'message' in result


def test_check_profile_use_returns_valid_structure():
	"""Test _check_profile_use returns a valid result."""
	result = doctor._check_profile_use()
	assert 'status' in result
	assert result['status'] in ('ok', 'missing')
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
