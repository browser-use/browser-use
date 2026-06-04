"""Setup command — post-install setup for browser-use CLI.

Covers everything install.sh does after the package is installed:
home directory, config file, Chromium, profile-use, cloudflared.
Interactive by default, --yes for CI.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _prompt(message: str, yes: bool) -> bool:
	"""Prompt user for confirmation. Returns True if --yes or user says yes."""
	if yes:
		return True
	try:
		reply = input(f'  {message} [Y/n] ').strip().lower()
		return reply in ('', 'y', 'yes')
	except (EOFError, KeyboardInterrupt):
		print()
		return False


def handle(yes: bool = False) -> dict:
	"""Run interactive setup."""
	from browser_use.skill_cli.utils import get_home_dir

	home_dir = get_home_dir()
	results: dict = {}
	step = 0
	total = 6

	print('\nBrowser-Use Setup')
	print('━━━━━━━━━━━━━━━━━\n')

	# Step 1: Home directory
	step += 1
	print(f'Step {step}/{total}: Home directory')
	if home_dir.exists():
		print(f'  ✓ {home_dir} exists')
	else:
		home_dir.mkdir(parents=True, exist_ok=True)
		print(f'  ✓ {home_dir} created')
	results['home_dir'] = 'ok'

	# Step 2: Config file
	step += 1
	config_path = home_dir / 'config.json'
	print(f'\nStep {step}/{total}: Config file')
	if config_path.exists():
		print(f'  ✓ {config_path} exists')
	else:
		config_path.write_text('{}\n')
		try:
			config_path.chmod(0o600)
		except OSError:
			pass
		print(f'  ✓ {config_path} created')
	results['config'] = 'ok'

	# Step 3: Chromium browser
	step += 1
	print(f'\nStep {step}/{total}: Chromium browser')
	chromium_installed = _check_chromium()
	if chromium_installed:
		print('  ✓ Chromium already installed')
		results['chromium'] = 'ok'
	else:
		if _prompt('Chromium is not installed (~300MB download). Install now?', yes):
			print('  ℹ Installing Chromium...')
			if _install_chromium():
				print('  ✓ Chromium installed')
				results['chromium'] = 'ok'
			else:
				print('  ✗ Chromium installation failed')
				results['chromium'] = 'failed'
		else:
			print('  ○ Skipped')
			results['chromium'] = 'skipped'

	# Step 4: Profile-use binary
	step += 1
	print(f'\nStep {step}/{total}: Profile-use binary')
	from browser_use.skill_cli.profile_use import get_profile_use_binary

	if get_profile_use_binary():
		print('  ✓ profile-use already installed')
		results['profile_use'] = 'ok'
	else:
		if _prompt('profile-use is not installed (needed for browser-use profile). Install now?', yes):
			print('  ℹ Downloading profile-use...')
			if _install_profile_use():
				print('  ✓ profile-use installed')
				results['profile_use'] = 'ok'
			else:
				print('  ✗ profile-use installation failed')
				results['profile_use'] = 'failed'
		else:
			print('  ○ Skipped')
			results['profile_use'] = 'skipped'

	# Step 5: Cloudflared
	step += 1
	print(f'\nStep {step}/{total}: Cloudflare tunnel (cloudflared)')
	if shutil.which('cloudflared'):
		print('  ✓ cloudflared already installed')
		results['cloudflared'] = 'ok'
	else:
		if _prompt('cloudflared is not installed (needed for browser-use tunnel). Install now?', yes):
			print('  ℹ Installing cloudflared...')
			if _install_cloudflared():
				print('  ✓ cloudflared installed')
				results['cloudflared'] = 'ok'
			else:
				print('  ✗ cloudflared installation failed')
				results['cloudflared'] = 'failed'
		else:
			print('  ○ Skipped')
			results['cloudflared'] = 'skipped'

	# Step 6: Validation
	step += 1
	print(f'\nStep {step}/{total}: Validation')
	from browser_use.skill_cli.config import CLI_DOCS_URL, get_config_display

	# Quick checks
	checks = {
		'package': _check_package(),
		'browser': 'ok' if _check_chromium() else 'missing',
		'profile_use': 'ok' if get_profile_use_binary() else 'missing',
		'cloudflared': 'ok' if shutil.which('cloudflared') else 'missing',
	}
	for name, status in checks.items():
		icon = '✓' if status == 'ok' else '○'
		print(f'  {icon} {name}: {status}')

	# Config display
	entries = get_config_display()
	print(f'\nConfig ({config_path}):')
	for entry in entries:
		if entry['is_set']:
			icon = '✓'
			val = 'set' if entry['sensitive'] else entry['value']
		else:
			icon = '○'
			val = entry['value'] if entry['value'] else 'not set'
		print(f'  {icon} {entry["key"]}: {val}')
	print(f'  Docs: {CLI_DOCS_URL}')

	print('\n━━━━━━━━━━━━━━━━━')
	print('Setup complete! Next: browser-use open https://example.com\n')

	results['status'] = 'success'
	return results


def _check_package() -> str:
	"""Check if browser-use package is importable."""
	try:
		import browser_use

		version = getattr(browser_use, '__version__', 'unknown')
		return f'browser-use {version}'
	except ImportError:
		return 'not installed'


def _check_chromium() -> bool:
	"""Check if playwright chromium is installed."""
	try:
		from browser_use.browser.profile import BrowserProfile

		BrowserProfile(headless=True)
		return True
	except Exception:
		return False


def _install_chromium() -> bool:
	"""Install Chromium via playwright."""
	try:
		cmd = [sys.executable, '-m', 'playwright', 'install', 'chromium']
		if sys.platform == 'linux':
			cmd.append('--with-deps')
		result = subprocess.run(cmd, timeout=300)
		return result.returncode == 0
	except Exception:
		return False


def _install_profile_use() -> bool:
	"""Download profile-use binary."""
	try:
		from browser_use.skill_cli.profile_use import download_profile_use

		download_profile_use()
		return True
	except Exception:
		return False


def _install_cloudflared() -> bool:
	"""Install cloudflared."""
	try:
		if sys.platform == 'darwin':
			result = subprocess.run(['brew', 'install', 'cloudflared'], timeout=120)
			return result.returncode == 0
		elif sys.platform == 'win32':
			result = subprocess.run(['winget', 'install', 'Cloudflare.cloudflared'], timeout=120)
			return result.returncode == 0
		else:
			# Linux: download binary + verify SHA256 checksum before installing
			import hashlib
			import platform
			import shutil
			import tempfile
			import urllib.request

			arch = 'arm64' if platform.machine() in ('aarch64', 'arm64') else 'amd64'
			base_url = f'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}'

			# Download to a temp file so we can verify before installing
			with tempfile.NamedTemporaryFile(delete=False, suffix='.tmp') as tmp:
				tmp_path = Path(tmp.name)
			try:
				urllib.request.urlretrieve(base_url, tmp_path)

				# Fetch checksum file published alongside the binary
				with urllib.request.urlopen(f'{base_url}.sha256sum') as resp:
					expected_sha256 = resp.read().decode().split()[0]

				# Verify integrity before touching the install destination
				actual_sha256 = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
				if actual_sha256 != expected_sha256:
					raise RuntimeError(
						f'cloudflared checksum mismatch — expected {expected_sha256}, got {actual_sha256}. '
						'The download may be corrupt or tampered with.'
					)

				dest = Path('/usr/local/bin/cloudflared')
				if not os.access('/usr/local/bin', os.W_OK):
					dest = Path.home() / '.local' / 'bin' / 'cloudflared'
					dest.parent.mkdir(parents=True, exist_ok=True)
				shutil.move(str(tmp_path), dest)
				dest.chmod(0o755)
			finally:
				tmp_path.unlink(missing_ok=True)
			return True
	except Exception:
		return False
