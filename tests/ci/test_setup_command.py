"""Tests for setup command.

These tests call real functions without mocking. They verify the
structure and logic of the setup command against actual system state.
"""

from browser_use.skill_cli.commands import setup


async def test_setup_returns_valid_structure():
	"""Test setup handle returns expected result structure."""
	result = await setup.handle(
		'setup',
		{
			'yes': True,
			'json': True,
		},
	)

	assert isinstance(result, dict)
	assert 'status' in result or 'error' in result

	if 'status' in result:
		assert result['status'] == 'success'
		assert 'checks' in result
		assert 'validation' in result


async def test_run_checks():
	"""Test run_checks returns expected structure."""
	checks = await setup.run_checks()

	assert isinstance(checks, dict)
	assert 'browser_use_package' in checks
	assert checks['browser_use_package']['status'] in ('ok', 'error')

	assert 'browser' in checks
	assert checks['browser']['status'] in ('ok', 'error')


async def test_check_browser():
	"""Test _check_browser returns valid structure."""
	result = await setup._check_browser()

	assert isinstance(result, dict)
	assert 'status' in result
	assert result['status'] in ('ok', 'error')
	assert 'message' in result


def test_plan_actions_no_actions_needed():
	"""Test plan_actions when everything is ok."""
	checks = {
		'browser_use_package': {'status': 'ok'},
		'browser': {'status': 'ok'},
	}

	actions = setup.plan_actions(checks, yes=False)
	assert actions == []


def test_plan_actions_install_browser():
	"""Test plan_actions when browser needs installation."""
	checks = {
		'browser_use_package': {'status': 'ok'},
		'browser': {'status': 'error'},
	}

	actions = setup.plan_actions(checks, yes=False)
	assert any(a['type'] == 'install_browser' for a in actions)


async def test_validate_setup():
	"""Test validate_setup returns expected structure."""
	results = await setup.validate_setup()

	assert isinstance(results, dict)
	assert 'browser_use_import' in results
	assert 'browser_available' in results
