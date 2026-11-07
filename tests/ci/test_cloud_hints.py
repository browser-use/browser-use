"""Cloud browser messages: a clear missing-key error and captcha hints only where they help."""

import logging

import pytest

from browser_use import Agent
from browser_use.browser.cloud.cloud import CloudBrowserAuthError, resolve_api_key
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.sync.auth import CloudAuthConfig
from tests.ci.conftest import create_mock_llm


@pytest.fixture
def records():
	"""Capture browser_use log records (the browser_use logger does not propagate to root)."""
	captured: list[logging.LogRecord] = []

	class _ListHandler(logging.Handler):
		def emit(self, record):
			captured.append(record)

	handler = _ListHandler(level=logging.DEBUG)
	logger = logging.getLogger('browser_use')
	logger.addHandler(handler)
	yield captured
	logger.removeHandler(handler)


@pytest.fixture
def no_api_key(monkeypatch, tmp_path):
	monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))


def test_resolve_api_key_prefers_env_then_saved_login(no_api_key, monkeypatch):
	assert resolve_api_key() is None

	CloudAuthConfig(api_token='saved-token', user_id='u', authorized_at=None).save_to_file()
	assert resolve_api_key() == 'saved-token'

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'env-token')
	assert resolve_api_key() == 'env-token'


async def test_use_cloud_without_key_fails_before_any_request(no_api_key):
	session = BrowserSession(use_cloud=True)
	with pytest.raises(CloudBrowserAuthError) as exc_info:
		await session.start()

	message = str(exc_info.value)
	assert 'BROWSER_USE_API_KEY is not set' in message
	assert 'https://cloud.browser-use.com/new-api-key?utm_source=oss&utm_medium=use_cloud' in message
	assert 'export BROWSER_USE_API_KEY=' in message


async def test_agent_logs_missing_key_once_without_traceback(no_api_key, records):
	agent = Agent(task='open example.com', llm=create_mock_llm(), browser_session=BrowserSession(use_cloud=True))

	with pytest.raises(CloudBrowserAuthError):
		await agent.run(max_steps=1)

	key_errors = [r for r in records if r.levelno >= logging.ERROR and 'BROWSER_USE_API_KEY is not set' in r.getMessage()]
	assert len(key_errors) == 1
	assert key_errors[0].exc_info is None
	assert not any('Open a short issue on GitHub' in r.getMessage() for r in records)


def _captcha_hints(records) -> int:
	return sum('blocked by a captcha' in r.getMessage() for r in records)


@pytest.mark.parametrize(
	'session_kwargs, expected',
	[
		({'browser_profile': BrowserProfile(headless=True)}, 1),
		({'use_cloud': True}, 0),
		({'cdp_url': 'wss://0e5c5a0e-1111-2222-3333-444455556666.cdp1.browser-use.com'}, 0),
		({'cdp_url': 'wss://connect.example-provider.com'}, 1),
		({'use_cloud': True, 'cdp_url': 'wss://connect.example-provider.com'}, 1),
	],
)
async def test_captcha_hint_only_for_non_browser_use_browsers_and_deduplicated(records, session_kwargs, expected):
	agent = Agent(task='t', llm=create_mock_llm(), browser_session=BrowserSession(**session_kwargs))

	agent._log_cloud_captcha_hint()
	agent._log_cloud_captcha_hint()

	assert _captcha_hints(records) == expected


async def test_cloud_hints_can_be_silenced(records, monkeypatch):
	monkeypatch.setenv('BROWSER_USE_CLOUD_HINTS', 'false')
	agent = Agent(task='t', llm=create_mock_llm(), browser_session=BrowserSession(browser_profile=BrowserProfile(headless=True)))

	agent._log_cloud_captcha_hint()

	assert _captcha_hints(records) == 0


async def test_local_launch_failure_hint_can_be_silenced(records, monkeypatch, tmp_path):
	monkeypatch.setenv('BROWSER_USE_CLOUD_HINTS', 'false')
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, executable_path=str(tmp_path / 'no-such-chrome')))

	try:
		with pytest.raises(Exception):
			await session.start()
	finally:
		await session.kill()

	assert not any('Local browser failed to start' in r.getMessage() for r in records)
