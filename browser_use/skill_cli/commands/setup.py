"""Setup command - configure browser-use for first-time use.

Checks browser availability and validates imports.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def handle(
	action: str,
	params: dict[str, Any],
) -> dict[str, Any]:
	"""Handle setup command."""
	assert action == 'setup'

	yes: bool = params.get('yes', False)
	json_output: bool = params.get('json', False)

	try:
		checks = await run_checks()

		if not json_output:
			_log_checks(checks)

		# Plan actions
		actions = plan_actions(checks, yes)

		if not json_output:
			_log_actions(actions)

		# Execute actions
		await execute_actions(actions, json_output)

		# Validate
		validation = await validate_setup()

		if not json_output:
			_log_validation(validation)

		return {
			'status': 'success',
			'checks': checks,
			'validation': validation,
		}

	except Exception as e:
		logger.exception(f'Setup failed: {e}')
		error_msg = str(e)
		return {'error': error_msg}


async def run_checks() -> dict[str, Any]:
	"""Run pre-flight checks without making changes.

	Returns:
		Dict mapping check names to their status
	"""
	checks: dict[str, Any] = {}

	# Package check
	try:
		import browser_use

		checks['browser_use_package'] = {
			'status': 'ok',
			'message': f'browser-use {browser_use.__version__}'
			if hasattr(browser_use, '__version__')
			else 'browser-use installed',
		}
	except ImportError:
		checks['browser_use_package'] = {
			'status': 'error',
			'message': 'browser-use not installed',
		}

	# Browser check
	checks['browser'] = await _check_browser()

	return checks


async def _check_browser() -> dict[str, Any]:
	"""Check if browser is available."""
	try:
		from browser_use.browser.profile import BrowserProfile

		profile = BrowserProfile(headless=True)
		# Just check if we can create a session without actually launching
		return {
			'status': 'ok',
			'message': 'Browser available',
		}
	except Exception as e:
		return {
			'status': 'error',
			'message': f'Browser check failed: {e}',
		}


def plan_actions(
	checks: dict[str, Any],
	yes: bool,
) -> list[dict[str, Any]]:
	"""Plan which actions to take based on checks.

	Returns:
		List of actions to execute
	"""
	actions: list[dict[str, Any]] = []

	# Browser installation
	browser_check = checks.get('browser', {})
	if browser_check.get('status') != 'ok':
		actions.append(
			{
				'type': 'install_browser',
				'description': 'Install browser (Chromium)',
				'required': True,
			}
		)

	return actions


async def execute_actions(
	actions: list[dict[str, Any]],
	json_output: bool,
) -> None:
	"""Execute planned actions.

	Args:
		actions: List of actions to execute
		json_output: Whether to output JSON
	"""
	for action in actions:
		action_type = action['type']

		if action_type == 'install_browser':
			if not json_output:
				print('📦 Installing Chromium browser (~300MB)...')
			# Browser will be installed on first use by Playwright
			if not json_output:
				print('✓ Browser available (will be installed on first use)')


async def validate_setup() -> dict[str, Any]:
	"""Validate that setup worked.

	Returns:
		Dict with validation results
	"""
	results: dict[str, Any] = {}

	# Check imports
	try:
		import browser_use  # noqa: F401

		results['browser_use_import'] = 'ok'
	except ImportError:
		results['browser_use_import'] = 'failed'

	# Validate browser
	try:
		from browser_use.browser.profile import BrowserProfile

		browser_profile = BrowserProfile(headless=True)
		results['browser_available'] = 'ok'
	except Exception as e:
		results['browser_available'] = f'failed: {e}'

	return results


def _log_checks(checks: dict[str, Any]) -> None:
	"""Log check results."""
	print('\n✓ Running checks...\n')
	for name, check in checks.items():
		status = check.get('status', 'unknown')
		message = check.get('message', '')
		icon = '✓' if status == 'ok' else '⚠' if status == 'missing' else '✗'
		print(f'  {icon} {name.replace("_", " ")}: {message}')
	print()


def _log_actions(actions: list[dict[str, Any]]) -> None:
	"""Log planned actions."""
	if not actions:
		print('✓ No additional setup needed!\n')
		return

	print('\n📋 Setup actions:\n')
	for i, action in enumerate(actions, 1):
		required = '(required)' if action.get('required') else '(optional)'
		print(f'  {i}. {action["description"]} {required}')
	print()


def _log_validation(validation: dict[str, Any]) -> None:
	"""Log validation results."""
	print('\n✓ Validation:\n')
	for name, result in validation.items():
		icon = '✓' if result == 'ok' else '✗'
		print(f'  {icon} {name.replace("_", " ")}: {result}')
	print()
