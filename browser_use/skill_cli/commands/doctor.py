"""Doctor command - check installation and dependencies.

Validates that browser-use is properly installed and all dependencies
are available. Provides helpful diagnostic information and fixes.
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


async def handle() -> dict[str, Any]:
	"""Run health checks and return results."""
	checks: dict[str, dict[str, Any]] = {}

	# 1. Package installation
	checks['package'] = _check_package()

	# 2. Browser availability
	checks['browser'] = _check_browser()

	# 3. Network connectivity (basic check)
	checks['network'] = await _check_network()

	# 4. Default Chrome extension cache/configuration
	checks['extensions'] = _check_extensions()

	# 5. Optional: cloudflared (for browser-use tunnel)
	checks['cloudflared'] = _check_cloudflared()

	# 6. Optional: profile-use (for browser-use profile)
	checks['profile_use'] = _check_profile_use()

	# Determine overall status
	all_ok = all(check.get('status') == 'ok' for check in checks.values())

	return {
		'status': 'healthy' if all_ok else 'issues_found',
		'checks': checks,
		'summary': _summarize_checks(checks),
	}


def _check_package() -> dict[str, Any]:
	"""Check if browser-use is installed."""
	try:
		import browser_use

		version = getattr(browser_use, '__version__', 'unknown')
		return {
			'status': 'ok',
			'message': f'browser-use {version}',
		}
	except ImportError:
		return {
			'status': 'error',
			'message': 'browser-use not installed',
			'fix': 'pip install browser-use',
		}


def _check_browser() -> dict[str, Any]:
	"""Check if browser is available."""
	try:
		from browser_use.browser.profile import BrowserProfile

		BrowserProfile(headless=True)  # verify import + constructor work
		return {
			'status': 'ok',
			'message': 'Browser profile available',
		}
	except Exception as e:
		return {
			'status': 'warning',
			'message': f'Browser may not be available: {e}',
			'note': 'Will be installed on first use',
		}


def _check_extensions() -> dict[str, Any]:
	"""Check default extension settings and cached unpacked extension manifests."""
	from browser_use.browser.profile import BrowserProfile, _get_enable_default_extensions_default
	from browser_use.config import CONFIG

	extensions_enabled = _get_enable_default_extensions_default()
	env_value = os.getenv('BROWSER_USE_DISABLE_EXTENSIONS')
	extensions_dir = CONFIG.BROWSER_USE_EXTENSIONS_DIR
	extensions_dir.mkdir(parents=True, exist_ok=True)

	manifest_dirs = sorted(path for path in extensions_dir.iterdir() if path.is_dir() and (path / 'manifest.json').exists())
	crx_files = sorted(extensions_dir.glob('*.crx'))

	details = {
		'enabled': extensions_enabled,
		'env': env_value,
		'cache_dir': str(extensions_dir),
		'unpacked_count': len(manifest_dirs),
		'crx_count': len(crx_files),
		'unpacked_extension_ids': [path.name for path in manifest_dirs],
	}
	note = f'Cache: {extensions_dir}; BROWSER_USE_DISABLE_EXTENSIONS={env_value or "unset"}'

	if not extensions_enabled:
		return {
			'status': 'warning',
			'message': 'Default extensions are disabled by BROWSER_USE_DISABLE_EXTENSIONS',
			'note': note,
			'details': details,
			'fix': 'Unset BROWSER_USE_DISABLE_EXTENSIONS or set it to 0/false to enable default extensions.',
		}

	invalid_manifests = [
		path.name for path in manifest_dirs if not BrowserProfile._check_extension_manifest_version(path, path.name)
	]
	details['invalid_manifest_ids'] = invalid_manifests

	if invalid_manifests:
		return {
			'status': 'warning',
			'message': f'Found {len(invalid_manifests)} cached extension(s) with invalid or unsupported manifests',
			'note': note,
			'details': details,
			'fix': f'Remove the affected directories from {extensions_dir} so Browser Use can download fresh copies.',
		}

	if manifest_dirs:
		return {
			'status': 'ok',
			'message': f'Default extensions enabled; found {len(manifest_dirs)} unpacked extension(s)',
			'note': note,
			'details': details,
		}

	return {
		'status': 'warning',
		'message': f'Default extensions enabled but no unpacked extensions were found in {extensions_dir}',
		'note': note,
		'details': details,
		'fix': 'Start a Browser with enable_default_extensions=True, then rerun doctor if Chrome still does not show them.',
	}


async def _check_network() -> dict[str, Any]:
	"""Check basic network connectivity."""
	try:
		import httpx

		async with httpx.AsyncClient(timeout=5.0) as client:
			# Just ping a reliable endpoint
			response = await client.head('https://api.github.com', follow_redirects=True)
			if response.status_code < 500:
				return {
					'status': 'ok',
					'message': 'Network connectivity OK',
				}
	except Exception as e:
		logger.debug(f'Network check failed: {e}')

	return {
		'status': 'warning',
		'message': 'Network connectivity check inconclusive',
		'note': 'Some features may not work offline',
	}


def _check_cloudflared() -> dict[str, Any]:
	"""Check if cloudflared is available (needed for browser-use tunnel)."""
	from browser_use.skill_cli.tunnel import get_tunnel_manager

	status = get_tunnel_manager().get_status()
	if status['available']:
		return {
			'status': 'ok',
			'message': f'cloudflared installed ({status["path"]})',
		}
	return {
		'status': 'missing',
		'message': 'cloudflared not installed (needed for browser-use tunnel)',
		'fix': 'Install cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/',
	}


def _check_profile_use() -> dict[str, Any]:
	"""Check if profile-use binary is available (needed for browser-use profile)."""
	from browser_use.skill_cli.profile_use import get_profile_use_binary

	binary = get_profile_use_binary()
	if binary:
		return {
			'status': 'ok',
			'message': f'profile-use installed ({binary})',
		}
	return {
		'status': 'missing',
		'message': 'profile-use not installed (needed for browser-use profile)',
		'fix': 'browser-use profile update',
	}


def _summarize_checks(checks: dict[str, dict[str, Any]]) -> str:
	"""Generate a summary of check results."""
	ok = sum(1 for c in checks.values() if c.get('status') == 'ok')
	warning = sum(1 for c in checks.values() if c.get('status') == 'warning')
	error = sum(1 for c in checks.values() if c.get('status') == 'error')
	missing = sum(1 for c in checks.values() if c.get('status') == 'missing')

	total = len(checks)

	parts = [f'{ok}/{total} checks passed']
	if warning > 0:
		parts.append(f'{warning} warnings')
	if error > 0:
		parts.append(f'{error} errors')
	if missing > 0:
		parts.append(f'{missing} missing')

	return ', '.join(parts)
