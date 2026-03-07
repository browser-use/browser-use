"""Tests for Safari session factory wiring."""

from unittest.mock import AsyncMock, patch

import pytest

from browser_use.browser.safari.session import SafariBrowserSession
from browser_use.browser.session import BrowserSession
from browser_use.skill_cli.sessions import SessionRegistry, create_browser_session


@pytest.mark.asyncio
async def test_create_browser_session_safari():
	"""Session factory should return a SafariBrowserSession for safari mode."""
	with patch('browser_use.skill_cli.install_config.is_mode_available', return_value=True):
		session = await create_browser_session('safari', headed=True, profile='Personal')

	assert isinstance(session, SafariBrowserSession)


@pytest.mark.asyncio
async def test_create_browser_session_safari_unavailable():
	"""Unavailable safari mode should raise the configured install error."""
	with (
		patch('browser_use.skill_cli.install_config.is_mode_available', return_value=False),
		patch(
			'browser_use.skill_cli.install_config.get_mode_unavailable_error',
			return_value='safari unavailable',
		),
	):
		with pytest.raises(RuntimeError, match='safari unavailable'):
			await create_browser_session('safari', headed=True, profile='Personal')


def test_from_backend_safari_profile_kwarg():
	"""from_backend should forward profile without duplicating the keyword."""
	session = BrowserSession.from_backend(browser_backend='safari', profile='Work')

	assert isinstance(session, SafariBrowserSession)
	assert session.browser_profile.automation_backend == 'safari'
	assert session.browser_profile.safari_profile == 'Work'


@pytest.mark.asyncio
async def test_session_registry_normalizes_safari_headed_flag():
	"""SessionRegistry should record Safari sessions as headed even when requested otherwise."""
	registry = SessionRegistry()
	browser_session = SafariBrowserSession(profile='active')
	object.__setattr__(browser_session, 'start', AsyncMock())

	with patch('browser_use.skill_cli.sessions.create_browser_session', AsyncMock(return_value=browser_session)) as factory:
		session_info = await registry.get_or_create('safari-test', 'safari', headed=False, profile='active')

	assert session_info.headed is True
	assert session_info.browser_session is browser_session
	factory.assert_awaited_once_with('safari', True, 'active')
