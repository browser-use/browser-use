"""Tests for CDP connection health verification and timeout recovery (issue #4579)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser_use.browser.session import BrowserSession
from browser_use.browser.watchdogs.dom_watchdog import DOMWatchdog


@pytest.mark.asyncio
async def test_session_health_flag_lifecycle():
	"""Verify _is_healthy controls is_cdp_connected and resets properly."""
	session = BrowserSession(headless=True)
	mock_client = MagicMock()
	mock_ws = MagicMock()
	from websockets.protocol import State

	mock_ws.state = State.OPEN
	mock_client.ws = mock_ws
	session._cdp_client_root = mock_client

	# Default: healthy and connected
	assert session.is_cdp_connected is True

	# Mark unhealthy → disconnected
	session._is_healthy = False
	assert session.is_cdp_connected is False

	# Reset restores health
	await session.reset()
	assert session._is_healthy is True


@pytest.mark.asyncio
async def test_verify_connection_health_success():
	"""verify_connection_health returns True when CDP ping succeeds."""
	session = BrowserSession(headless=True)
	mock_client = MagicMock()
	mock_ws = MagicMock()
	from websockets.protocol import State

	mock_ws.state = State.OPEN
	mock_client.ws = mock_ws
	mock_version = AsyncMock(return_value={'protocolVersion': '1.3'})
	mock_client.send = MagicMock()
	mock_client.send.Browser = MagicMock()
	mock_client.send.Browser.getVersion = mock_version
	session._cdp_client_root = mock_client

	assert await session.verify_connection_health() is True
	mock_version.assert_called_once()


@pytest.mark.asyncio
async def test_verify_connection_health_timeout():
	"""verify_connection_health returns False when CDP ping hangs."""
	session = BrowserSession(headless=True)
	mock_client = MagicMock()
	mock_ws = MagicMock()
	from websockets.protocol import State

	mock_ws.state = State.OPEN
	mock_client.ws = mock_ws

	async def mock_hang():
		await asyncio.sleep(5.0)
		return {}

	mock_client.send = MagicMock()
	mock_client.send.Browser = MagicMock()
	mock_client.send.Browser.getVersion = mock_hang
	session._cdp_client_root = mock_client

	assert await session.verify_connection_health() is False


@pytest.mark.asyncio
async def test_dom_watchdog_timeout_marks_unhealthy():
	"""DOMWatchdog timeout handlers mark session unhealthy and raise ConnectionError."""
	session = BrowserSession(headless=True)
	mock_client = MagicMock()
	mock_ws = MagicMock()
	from websockets.protocol import State

	mock_ws.state = State.OPEN
	mock_client.ws = mock_ws
	session._cdp_client_root = mock_client

	watchdog = DOMWatchdog(event_bus=session.event_bus, browser_session=session)

	async def mock_timeout(*args, **kwargs):
		raise TimeoutError('CDP call timed out')

	with patch.object(BrowserSession, 'get_or_create_cdp_session', mock_timeout):
		with pytest.raises(ConnectionError, match='CDP timed out'):
			await watchdog._get_pending_network_requests()
		assert session._is_healthy is False
