from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog


@pytest.mark.asyncio
async def test_wait_for_cdp_url_returns_ws_url():
	"""
	Regression test for #3718: Verify that _wait_for_cdp_url returns the WebSocket URL
	directly from the /json/version response.
	"""
	expected_ws_url = 'ws://127.0.0.1:9222/devtools/browser/uuid'

	# 1. Mock the Response object
	# It needs .json() to be awaitable
	mock_response = MagicMock()
	mock_response.status = 200
	mock_response.json = AsyncMock(return_value={'webSocketDebuggerUrl': expected_ws_url})

	# 2. Mock the Context Manager returned by session.get()
	# It needs __aenter__ and __aexit__ to be awaitable
	mock_context = MagicMock()
	mock_context.__aenter__ = AsyncMock(return_value=mock_response)
	mock_context.__aexit__ = AsyncMock(return_value=None)

	# 3. Mock the Session object
	# It acts as an async context manager itself (async with ClientSession())
	mock_session = MagicMock()
	mock_session.__aenter__ = AsyncMock(return_value=mock_session)
	mock_session.__aexit__ = AsyncMock(return_value=None)
	# .get() is synchronous and returns the request context manager
	mock_session.get = MagicMock(return_value=mock_context)

	# 4. Patch aiohttp.ClientSession
	# ClientSession() constructor returns our mock_session
	with patch('aiohttp.ClientSession', return_value=mock_session):
		ws_url = await LocalBrowserWatchdog._wait_for_cdp_url(port=9222, process=None, timeout=1)

		assert ws_url == expected_ws_url
		assert mock_response.json.called


@pytest.mark.asyncio
async def test_wait_for_cdp_url_retries_on_invalid_json():
	"""Verify that _wait_for_cdp_url retries if JSON parsing fails."""

	expected_ws_url = 'ws://127.0.0.1:9222/devtools/browser/uuid'

	# Setup mocks for Failure case
	mock_response_fail = MagicMock()
	mock_response_fail.status = 200
	mock_response_fail.json = AsyncMock(side_effect=Exception('JSON decode error'))

	mock_ctx_fail = MagicMock()
	mock_ctx_fail.__aenter__ = AsyncMock(return_value=mock_response_fail)
	mock_ctx_fail.__aexit__ = AsyncMock(return_value=None)

	# Setup mocks for Success case
	mock_response_success = MagicMock()
	mock_response_success.status = 200
	mock_response_success.json = AsyncMock(return_value={'webSocketDebuggerUrl': expected_ws_url})

	mock_ctx_success = MagicMock()
	mock_ctx_success.__aenter__ = AsyncMock(return_value=mock_response_success)
	mock_ctx_success.__aexit__ = AsyncMock(return_value=None)

	# Session mock
	mock_session = MagicMock()
	mock_session.__aenter__ = AsyncMock(return_value=mock_session)
	mock_session.__aexit__ = AsyncMock(return_value=None)
	# get() returns fail context then success context
	mock_session.get = MagicMock(side_effect=[mock_ctx_fail, mock_ctx_success])

	with patch('aiohttp.ClientSession', return_value=mock_session):
		# Pass a mock process
		mock_process = MagicMock()
		mock_process.returncode = None

		ws_url = await LocalBrowserWatchdog._wait_for_cdp_url(port=9222, process=mock_process, timeout=2)  # type: ignore

		assert ws_url == expected_ws_url
		assert mock_session.get.call_count == 2
