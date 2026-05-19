"""Tests for browser-use cloud connect CLI command."""

import subprocess
import sys
from unittest.mock import AsyncMock

from browser_use.browser.cloud.views import CloudBrowserResponse
from browser_use.skill_cli.sessions import create_browser_session


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


def _cloud_browser_response() -> CloudBrowserResponse:
	return CloudBrowserResponse(
		id='browser-test',
		status='active',
		liveUrl='https://live.browser-use.com/session',
		cdpUrl='wss://browser-use.test/cdp',
		timeoutAt='2026-01-01T00:15:00Z',
		startedAt='2026-01-01T00:00:00Z',
		finishedAt=None,
	)


async def test_cloud_connect_browser_uses_env_api_key_without_saved_login(tmp_path, monkeypatch):
	"""Cloud connect daemon should accept BROWSER_USE_API_KEY without saved login config."""
	monkeypatch.setenv('BROWSER_USE_HOME', str(tmp_path))
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'sk-env-key')

	browser_session = await create_browser_session(
		headed=False,
		profile=None,
		use_cloud=True,
		cloud_profile_id='profile-existing',
	)
	browser_session._cloud_browser_client.create_browser = AsyncMock(return_value=_cloud_browser_response())

	await browser_session._provision_cloud_browser()

	browser_session._cloud_browser_client.create_browser.assert_awaited_once()
	assert browser_session.browser_profile.cdp_url == 'wss://browser-use.test/cdp'
	assert browser_session.browser_profile.is_local is False


async def test_cloud_connect_recreates_invalid_profile_with_env_api_key(tmp_path, monkeypatch):
	"""Cloud connect profile recovery should use BROWSER_USE_API_KEY when config has no api_key."""
	monkeypatch.setenv('BROWSER_USE_HOME', str(tmp_path))
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'sk-env-key')

	created_with_keys: list[str] = []

	def create_profile(api_key: str) -> str:
		created_with_keys.append(api_key)
		return 'profile-recreated'

	monkeypatch.setattr('browser_use.skill_cli.commands.cloud._create_cloud_profile_inner', create_profile)

	browser_session = await create_browser_session(
		headed=False,
		profile=None,
		use_cloud=True,
		cloud_profile_id='profile-stale',
	)
	browser_session._cloud_browser_client.create_browser = AsyncMock(
		side_effect=[RuntimeError('profile invalid: 422'), _cloud_browser_response()]
	)

	await browser_session._provision_cloud_browser()

	assert created_with_keys == ['sk-env-key']
	assert browser_session._cloud_browser_client.create_browser.await_count == 2
	retry_request = browser_session._cloud_browser_client.create_browser.await_args_list[1].args[0]
	assert retry_request.profile_id == 'profile-recreated'
	assert browser_session.browser_profile.cdp_url == 'wss://browser-use.test/cdp'
