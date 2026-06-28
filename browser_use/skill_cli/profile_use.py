"""Profile-use Go binary management.

Downloads, locates, and invokes the profile-use Go binary as a managed
subcommand of `browser-use profile`. The binary is always managed at
~/.browser-use/bin/profile-use — standalone installs on $PATH are independent.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def get_profile_use_binary() -> Path | None:
	"""Return path to managed profile-use binary, or None if not installed."""
	from browser_use.skill_cli.utils import get_bin_dir

	binary = get_bin_dir() / ('profile-use.exe' if sys.platform == 'win32' else 'profile-use')
	if binary.is_file() and os.access(str(binary), os.X_OK):
		return binary
	return None


def download_profile_use() -> Path:
	"""Download profile-use binary via the official install script.

	Runs: curl -fsSL https://browser-use.com/profile/cli/install.sh | sh
	with INSTALL_DIR set to ~/.browser-use/bin/

	Raises RuntimeError if download fails.
	"""
	from browser_use.skill_cli.utils import get_bin_dir

	if not shutil.which('curl'):
		raise RuntimeError(
			'curl is required to download profile-use.\n'
			'Install curl and try again, or install profile-use manually:\n'
			'  curl -fsSL https://browser-use.com/profile/cli/install.sh | sh'
		)

	bin_dir = get_bin_dir()
	env = {**os.environ, 'INSTALL_DIR': str(bin_dir)}

	result = subprocess.run(
		['sh', '-c', 'curl -fsSL https://browser-use.com/profile/cli/install.sh | sh'],
		env=env,
	)

	if result.returncode != 0:
		raise RuntimeError(
			'Failed to download profile-use. Try installing manually:\n  curl -fsSL https://browser-use.com/profile/cli/install.sh | sh'
		)

	binary = get_profile_use_binary()
	if binary is None:
		raise RuntimeError('Download appeared to succeed but binary not found at expected location.')

	return binary


def ensure_profile_use() -> Path:
	"""Return path to profile-use binary, downloading if not present."""
	binary = get_profile_use_binary()
	if binary is not None:
		return binary

	print('profile-use not found, downloading...', file=sys.stderr)
	return download_profile_use()


def run_profile_use(args: list[str]) -> int:
	"""Execute profile-use with the given arguments.

	Handles the 'update' subcommand specially by re-running the install script.
	Passes BROWSER_USE_CONFIG_DIR so profile-use shares config with browser-use.
	"""
	# Handle 'update' subcommand — re-download latest binary
	if args and args[0] == 'update':
		try:
			download_profile_use()
			print('profile-use updated successfully')
			return 0
		except RuntimeError as e:
			print(f'Error: {e}', file=sys.stderr)
			return 1

	try:
		binary = ensure_profile_use()
	except RuntimeError as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	from browser_use.skill_cli.utils import get_home_dir

	env = {**os.environ, 'BROWSER_USE_CONFIG_DIR': str(get_home_dir())}
	# Forward API key from config.json for profile-use binary
	from browser_use.skill_cli.config import get_config_value

	api_key = get_config_value('api_key')
	if api_key:
		env['BROWSER_USE_API_KEY'] = str(api_key)

	return subprocess.call([str(binary)] + args, env=env)
