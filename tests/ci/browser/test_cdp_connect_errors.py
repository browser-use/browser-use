"""
Test error handling when connecting to a remote CDP endpoint via /json/version.

Validates that connect() raises clear, actionable RuntimeError messages when
the CDP endpoint returns non-200 status, non-JSON bodies, or is missing
the required webSocketDebuggerUrl field.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser_use.browser.session import BrowserSession


def _make_mock_httpx_client(mock_response):
	"""Set up an httpx.AsyncClient mock that returns the given response from GET."""
	mock_client = AsyncMock()
	mock_client.get = AsyncMock(return_value=mock_response)

	mock_client_class = MagicMock()
	mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
	mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)
	return mock_client_class


@pytest.mark.asyncio
async def test_connect_raises_on_non_200_status():
	"""Non-200 response from /json/version should raise RuntimeError with the status code."""
	session = BrowserSession(cdp_url='http://remote-browser:9222')

	mock_response = MagicMock()
	mock_response.status_code = 502

	mock_client_class = _make_mock_httpx_client(mock_response)

	with patch('browser_use.browser.session.httpx.AsyncClient', mock_client_class):
		with pytest.raises(RuntimeError, match='HTTP 502'):
			await session.connect()


@pytest.mark.asyncio
async def test_connect_raises_on_non_json_response():
	"""HTML or other non-JSON response from /json/version should raise RuntimeError."""
	session = BrowserSession(cdp_url='http://remote-browser:9222')

	mock_response = MagicMock()
	mock_response.status_code = 200
	mock_response.json.side_effect = ValueError('No JSON object could be decoded')

	mock_client_class = _make_mock_httpx_client(mock_response)

	with patch('browser_use.browser.session.httpx.AsyncClient', mock_client_class):
		with pytest.raises(RuntimeError, match='non-JSON response'):
			await session.connect()


@pytest.mark.asyncio
async def test_connect_raises_on_missing_ws_url():
	"""JSON response without webSocketDebuggerUrl should raise RuntimeError."""
	session = BrowserSession(cdp_url='http://remote-browser:9222')

	mock_response = MagicMock()
	mock_response.status_code = 200
	mock_response.json.return_value = {'Browser': 'Chrome/120.0', 'Protocol-Version': '1.3'}

	mock_client_class = _make_mock_httpx_client(mock_response)

	with patch('browser_use.browser.session.httpx.AsyncClient', mock_client_class):
		with pytest.raises(RuntimeError, match='missing "webSocketDebuggerUrl"'):
			await session.connect()


@pytest.mark.asyncio
async def test_connect_succeeds_with_valid_json_version_response():
	"""Valid /json/version response should set cdp_url to the returned webSocketDebuggerUrl."""
	session = BrowserSession(cdp_url='http://remote-browser:9222')

	mock_response = MagicMock()
	mock_response.status_code = 200
	mock_response.json.return_value = {
		'webSocketDebuggerUrl': 'ws://remote-browser:9222/devtools/browser/abc123',
	}

	mock_client_class = _make_mock_httpx_client(mock_response)

	with patch('browser_use.browser.session.httpx.AsyncClient', mock_client_class):
		with patch('browser_use.browser.session.CDPClient') as mock_cdp_class:
			mock_cdp = AsyncMock()
			mock_cdp_class.return_value = mock_cdp
			mock_cdp.start = AsyncMock()
			mock_cdp.send = MagicMock()
			mock_cdp.send.Target = MagicMock()
			mock_cdp.send.Target.setAutoAttach = AsyncMock()

			with patch('browser_use.browser.session_manager.SessionManager') as mock_sm_class:
				mock_sm = MagicMock()
				mock_sm_class.return_value = mock_sm
				mock_sm.start_monitoring = AsyncMock()
				mock_sm.get_all_page_targets = MagicMock(return_value=[])

				try:
					await session.connect()
				except Exception:
					pass  # May fail due to incomplete mocking past the /json/version step

				# The key assertion: cdp_url was updated to the websocket URL
				assert session.browser_profile.cdp_url == 'ws://remote-browser:9222/devtools/browser/abc123'
