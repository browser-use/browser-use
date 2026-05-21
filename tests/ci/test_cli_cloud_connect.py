"""Tests for browser-use cloud connect CLI command."""

import subprocess
import sys


def run_cli(*args: str, env_override: dict | None = None) -> subprocess.CompletedProcess:
	"""Run the CLI as a subprocess, returning the result."""
	import os

	env = os.environ.copy()
	env.pop('BROWSER_USE_API_KEY', None)
	if env_override:
		env.update(env_override)

	return subprocess.run(
		[sys.executable, '-m', 'browser_use.skill_cli.main', *args],
		capture_output=True,
		text=True,
		env=env,
		timeout=15,
	)


def test_cloud_connect_mutual_exclusivity_cdp_url():
	"""cloud connect + --cdp-url should error."""
	result = run_cli('--cdp-url', 'http://localhost:9222', 'cloud', 'connect')
	assert result.returncode == 1
	assert 'mutually exclusive' in result.stderr.lower()


def test_cloud_connect_mutual_exclusivity_profile():
	"""cloud connect + --profile should error."""
	result = run_cli('--profile', 'Default', 'cloud', 'connect')
	assert result.returncode == 1
	assert 'mutually exclusive' in result.stderr.lower()


def test_cloud_connect_shows_in_usage():
	"""cloud help should list connect."""
	result = run_cli('cloud', '--help')
	assert 'connect' in result.stdout.lower()


def test_cloud_connect_help_shows_in_epilog():
	"""Main --help epilog should mention cloud connect."""
	result = run_cli('--help')
	assert 'cloud connect' in result.stdout.lower()
