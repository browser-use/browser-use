"""Tests for browser-use CLI config commands."""

import os
import subprocess
import sys
from pathlib import Path


def run_cli(*args: str, browser_use_home: Path) -> subprocess.CompletedProcess:
	"""Run the CLI with an isolated browser-use home directory."""
	env = os.environ.copy()
	env['BROWSER_USE_HOME'] = str(browser_use_home)
	env.pop('BROWSER_USE_API_KEY', None)

	return subprocess.run(
		[sys.executable, '-m', 'browser_use.skill_cli.main', *args],
		capture_output=True,
		text=True,
		env=env,
		timeout=15,
	)


def test_config_set_masks_sensitive_api_key(tmp_path):
	"""config set should not echo the raw API key back to stdout."""
	secret = 'sk-browser-use-test-secret'

	result = run_cli('config', 'set', 'api_key', secret, browser_use_home=tmp_path)

	assert result.returncode == 0
	assert 'api_key = set' in result.stdout
	assert secret not in result.stdout
	assert secret not in result.stderr


def test_config_set_keeps_non_sensitive_values_visible(tmp_path):
	"""Non-sensitive config values should keep the existing explicit output."""
	result = run_cli('config', 'set', 'cloud_connect_proxy', 'us', browser_use_home=tmp_path)

	assert result.returncode == 0
	assert 'cloud_connect_proxy = us' in result.stdout
