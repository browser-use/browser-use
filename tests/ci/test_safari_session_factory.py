"""Tests for Safari session factory wiring."""

from unittest.mock import patch

import pytest

from browser_use.browser.safari.session import SafariBrowserSession
from browser_use.skill_cli.sessions import create_browser_session


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
