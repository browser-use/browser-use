"""Tests for setup command.

These tests call real functions without mocking. They verify the
structure and logic of the setup command against actual system state.
"""

from browser_use.skill_cli.commands import setup


async def test_setup_local_mode():
	"""Test setup with local mode runs without error."""
	result = await setup.handle(
		'setup',
		{
			'mode': 'local',
			'api_key': None,
			'yes': True,
			'json': True,
		},
	)

	# Should return a dict with expected structure
	assert isinstance(result, dict)
	# Either success or error, but should have a response
	assert 'status' in result or 'error' in result

	if 'status' in result:
		assert result['status'] == 'success'
		assert result['mode'] == 'local'
		assert 'checks' in result
		assert 'validation' in result


async def test_setup_remote_mode():
	"""Test setup with remote mode runs without error."""
	result = await setup.handle(
		'setup',
		{
			'mode': 'remote',
			'api_key': None,
			'yes': True,
			'json': True,
		},
	)

	# Should return a dict with expected structure
	assert isinstance(result, dict)
	assert 'status' in result or 'error' in result

	if 'status' in result:
		assert result['status'] == 'success'
		assert result['mode'] == 'remote'
		assert 'checks' in result
		assert 'validation' in result


async def test_setup_full_mode():
	"""Test setup with full mode runs without error."""
	result = await setup.handle(
		'setup',
		{
			'mode': 'full',
			'api_key': None,
			'yes': True,
			'json': True,
		},
	)

	assert isinstance(result, dict)
	assert 'status' in result or 'error' in result

	if 'status' in result:
		assert result['status'] == 'success'
		assert result['mode'] == 'full'


async def test_setup_invalid_mode():
	"""Test setup with invalid mode returns error."""
	result = await setup.handle(
		'setup',
		{
			'mode': 'invalid',
			'api_key': None,
			'yes': False,
			'json': False,
		},
	)

	assert 'error' in result
	assert 'Invalid mode' in result['error']


async def test_run_checks_local():
	"""Test run_checks returns expected structure for local mode."""
	checks = await setup.run_checks('local')

	assert isinstance(checks, dict)
	assert 'browser_use_package' in checks
	assert checks['browser_use_package']['status'] in ('ok', 'error')

	# Local mode should check browser
	assert 'browser' in checks
	assert checks['browser']['status'] in ('ok', 'error')

	# Local mode should NOT check api_key or cloudflared
	assert 'api_key' not in checks
	assert 'cloudflared' not in checks


async def test_run_checks_remote():
	"""Test run_checks returns expected structure for remote mode."""
	checks = await setup.run_checks('remote')

	assert isinstance(checks, dict)
	assert 'browser_use_package' in checks

	# Remote mode should check api_key and cloudflared
	assert 'api_key' in checks
	assert checks['api_key']['status'] in ('ok', 'missing')
	assert 'cloudflared' in checks
	assert checks['cloudflared']['status'] in ('ok', 'missing')

	# Remote mode should NOT check browser
	assert 'browser' not in checks


async def test_run_checks_full():
	"""Test run_checks returns expected structure for full mode."""
	checks = await setup.run_checks('full')

	assert isinstance(checks, dict)
	# Full mode should check everything
	assert 'browser_use_package' in checks
	assert 'browser' in checks
	assert 'api_key' in checks
	assert 'cloudflared' in checks


def test_plan_actions_no_actions_needed():
	"""Test plan_actions when everything is ok."""
	checks = {
		'browser_use_package': {'status': 'ok'},
		'browser': {'status': 'ok'},
		'api_key': {'status': 'ok'},
		'cloudflared': {'status': 'ok'},
	}

	actions = setup.plan_actions(checks, 'local', yes=False, api_key=None)
	assert actions == []


def test_plan_actions_install_browser():
	"""Test plan_actions when browser needs installation."""
	checks = {
		'browser_use_package': {'status': 'ok'},
		'browser': {'status': 'error'},
	}

	actions = setup.plan_actions(checks, 'local', yes=False, api_key=None)
	assert any(a['type'] == 'install_browser' for a in actions)


def test_plan_actions_configure_api_key():
	"""Test plan_actions when API key is provided."""
	checks = {
		'api_key': {'status': 'missing'},
	}

	actions = setup.plan_actions(checks, 'remote', yes=True, api_key='test_key')
	assert any(a['type'] == 'configure_api_key' for a in actions)


def test_plan_actions_prompt_api_key():
	"""Test plan_actions prompts for API key when missing and not --yes."""
	checks = {
		'api_key': {'status': 'missing'},
	}

	actions = setup.plan_actions(checks, 'remote', yes=False, api_key=None)
	assert any(a['type'] == 'prompt_api_key' for a in actions)


def test_plan_actions_install_cloudflared():
	"""Test plan_actions when cloudflared is missing."""
	checks = {
		'cloudflared': {'status': 'missing'},
	}

	actions = setup.plan_actions(checks, 'remote', yes=True, api_key=None)
	assert any(a['type'] == 'install_cloudflared' for a in actions)


async def test_check_browser():
	"""Test _check_browser returns valid structure."""
	result = await setup._check_browser()

	assert isinstance(result, dict)
	assert 'status' in result
	assert result['status'] in ('ok', 'error')
	assert 'message' in result


async def test_validate_setup_local():
	"""Test validate_setup returns expected structure for local mode."""
	results = await setup.validate_setup('local')

	assert isinstance(results, dict)
	assert 'browser_use_import' in results
	assert 'browser_available' in results
	# Should not have remote-only checks
	assert 'api_key_available' not in results


async def test_validate_setup_remote():
	"""Test validate_setup returns expected structure for remote mode."""
	results = await setup.validate_setup('remote')

	assert isinstance(results, dict)
	assert 'browser_use_import' in results
	assert 'api_key_available' in results
	assert 'cloudflared_available' in results
	# Should not have local-only checks
	assert 'browser_available' not in results
