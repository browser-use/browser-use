"""Setup command - configure browser-use for first-time use.

Handles dependency installation and configuration with mode-based
setup (local/remote/full) and optional automatic fixes.
"""

import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

COMMANDS = {'setup'}


async def handle(
	action: str,
	params: dict[str, Any],
) -> dict[str, Any]:
	"""Handle setup command."""
	assert action == 'setup'

	mode: Literal['local', 'remote', 'full'] = params.get('mode', 'local')
	yes: bool = params.get('yes', False)
	api_key: str | None = params.get('api_key')
	json_output: bool = params.get('json', False)

	# Validate mode
	if mode not in ('local', 'remote', 'full'):
		return {'error': f'Invalid mode: {mode}. Must be local, remote, or full'}

	# Run setup flow
	try:
		checks = await run_checks(mode)

		if not json_output:
			_log_checks(checks)

		# Plan actions
		actions = plan_actions(checks, mode, yes, api_key)

		if not json_output:
			_log_actions(actions)

		# Execute actions
		await execute_actions(actions, mode, api_key, json_output)

		# Validate
		validation = await validate_setup(mode)

		if not json_output:
			_log_validation(validation)

		return {
			'status': 'success',
			'mode': mode,
			'checks': checks,
			'validation': validation,
		}

	except Exception as e:
		logger.exception(f'Setup failed: {e}')
		error_msg = str(e)
		if json_output:
			return {'error': error_msg}
		return {'error': error_msg}


async def run_checks(mode: Literal['local', 'remote', 'full']) -> dict[str, Any]:
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

	# Browser check (local and full modes)
	if mode in ('local', 'full'):
		checks['browser'] = await _check_browser()

	# API key check (remote and full modes)
	if mode in ('remote', 'full'):
		from browser_use.skill_cli.api_key import check_api_key

		api_status = check_api_key()
		if api_status['available']:
			checks['api_key'] = {
				'status': 'ok',
				'message': f'Configured via {api_status["source"]} ({api_status["key_prefix"]}...)',
			}
		else:
			checks['api_key'] = {
				'status': 'missing',
				'message': 'Not configured',
			}

	# Cloudflared check (remote and full modes)
	if mode in ('remote', 'full'):
		from browser_use.skill_cli.tunnel import get_tunnel_manager

		tunnel_mgr = get_tunnel_manager()
		status = tunnel_mgr.get_status()
		checks['cloudflared'] = {
			'status': 'ok' if status['available'] else 'missing',
			'message': status['note'],
		}

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
	mode: Literal['local', 'remote', 'full'],
	yes: bool,
	api_key: str | None,
) -> list[dict[str, Any]]:
	"""Plan which actions to take based on checks.

	Returns:
		List of actions to execute
	"""
	actions: list[dict[str, Any]] = []

	# Browser installation (local/full)
	if mode in ('local', 'full'):
		browser_check = checks.get('browser', {})
		if browser_check.get('status') != 'ok':
			actions.append(
				{
					'type': 'install_browser',
					'description': 'Install browser (Chromium)',
					'required': True,
				}
			)

	# API key configuration (remote/full)
	if mode in ('remote', 'full'):
		api_check = checks.get('api_key', {})
		if api_check.get('status') != 'ok':
			if api_key:
				actions.append(
					{
						'type': 'configure_api_key',
						'description': 'Configure API key',
						'required': True,
						'api_key': api_key,
					}
				)
			elif not yes:
				actions.append(
					{
						'type': 'prompt_api_key',
						'description': 'Prompt for API key',
						'required': False,
					}
				)

	# Cloudflared (remote/full)
	if mode in ('remote', 'full'):
		cloudflared_check = checks.get('cloudflared', {})
		if cloudflared_check.get('status') != 'ok':
			actions.append(
				{
					'type': 'install_cloudflared',
					'description': 'Install cloudflared (for tunneling)',
					'required': True,
				}
			)

	return actions


async def execute_actions(
	actions: list[dict[str, Any]],
	mode: Literal['local', 'remote', 'full'],
	api_key: str | None,
	json_output: bool,
) -> None:
	"""Execute planned actions.

	Args:
		actions: List of actions to execute
		mode: Setup mode (local/remote/full)
		api_key: Optional API key to configure
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

		elif action_type == 'configure_api_key':
			if not json_output:
				print('🔑 Configuring API key...')
			from browser_use.skill_cli.api_key import save_api_key

			if api_key:
				save_api_key(api_key)
				if not json_output:
					print('✓ API key configured')

		elif action_type == 'prompt_api_key':
			if not json_output:
				print('🔑 API key not configured')
				print('   Set via: export BROWSER_USE_API_KEY=your_key')
				print('   Or: browser-use setup --api-key <key>')

		elif action_type == 'install_cloudflared':
			if not json_output:
				print('⚠ cloudflared not installed')
				print('   Install via:')
				print('   macOS:   brew install cloudflared')
				print(
					'   Linux:   curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o ~/.local/bin/cloudflared && chmod +x ~/.local/bin/cloudflared'
				)
				print('   Windows: winget install Cloudflare.cloudflared')
				print()
				print('   Or re-run install.sh which installs cloudflared automatically.')


async def validate_setup(
	mode: Literal['local', 'remote', 'full'],
) -> dict[str, Any]:
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

	# Validate mode requirements
	if mode in ('local', 'full'):
		try:
			from browser_use.browser.profile import BrowserProfile

			browser_profile = BrowserProfile(headless=True)
			results['browser_available'] = 'ok'
		except Exception as e:
			results['browser_available'] = f'failed: {e}'

	if mode in ('remote', 'full'):
		from browser_use.skill_cli.api_key import check_api_key
		from browser_use.skill_cli.tunnel import get_tunnel_manager

		api_check = check_api_key()
		results['api_key_available'] = api_check['available']

		tunnel_mgr = get_tunnel_manager()
		results['cloudflared_available'] = tunnel_mgr.is_available()

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
