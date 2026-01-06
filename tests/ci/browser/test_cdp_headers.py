"""
Test that headers are properly passed to CDPClient for authenticated remote browser connections.

This tests the fix for: When using browser-use with remote browser services that require
authentication headers, these headers need to be included in the WebSocket handshake.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession


def test_browser_profile_headers_attribute():
	"""Test that BrowserProfile correctly stores headers attribute."""
	test_headers = {'Authorization': 'Bearer token123', 'X-API-Key': 'key456'}

	profile = BrowserProfile(headers=test_headers)

	# Verify headers are stored correctly
	assert profile.headers == test_headers

	# Test with profile without headers
	profile_no_headers = BrowserProfile()
	assert profile_no_headers.headers is None


def test_browser_profile_headers_inherited():
	"""Test that BrowserSession can access headers from its profile."""
	test_headers = {'Authorization': 'Bearer test-token'}

	session = BrowserSession(cdp_url='wss://example.com/cdp', headers=test_headers)

	assert session.browser_profile.headers == test_headers


@pytest.mark.asyncio
async def test_cdp_client_headers_passed_on_connect():
	"""Test that headers from BrowserProfile are passed to CDPClient on connect()."""
	test_headers = {
		'Authorization': 'AWS4-HMAC-SHA256 Credential=test...',
		'X-Amz-Date': '20250914T163733Z',
		'X-Amz-Security-Token': 'test-token',
		'Host': 'remote-browser.example.com',
	}

	session = BrowserSession(cdp_url='wss://remote-browser.example.com/cdp', headers=test_headers)

	with patch('browser_use.browser.session.CDPClient') as mock_cdp_client_class:
		# Setup mock CDPClient instance
		mock_cdp_client = AsyncMock()
		mock_cdp_client_class.return_value = mock_cdp_client
		mock_cdp_client.start = AsyncMock()
		mock_cdp_client.stop = AsyncMock()

		# Mock CDP methods
		mock_cdp_client.send = MagicMock()
		mock_cdp_client.send.Target = MagicMock()
		mock_cdp_client.send.Target.setAutoAttach = AsyncMock()
		mock_cdp_client.send.Target.getTargets = AsyncMock(return_value={'targetInfos': []})
		mock_cdp_client.send.Target.createTarget = AsyncMock(return_value={'targetId': 'test-target-id'})

		# Mock SessionManager (imported inside connect() from browser_use.browser.session_manager)
		with patch('browser_use.browser.session_manager.SessionManager') as mock_session_manager_class:
			mock_session_manager = MagicMock()
			mock_session_manager_class.return_value = mock_session_manager
			mock_session_manager.start_monitoring = AsyncMock()
			mock_session_manager.get_all_page_targets = MagicMock(return_value=[])

			try:
				await session.connect()
			except Exception:
				# May fail due to incomplete mocking, but we can still verify the key assertion
				pass

			# Verify CDPClient was instantiated with the headers
			mock_cdp_client_class.assert_called_once()
			call_kwargs = mock_cdp_client_class.call_args

			# Check positional args and keyword args
			assert call_kwargs[0][0] == 'wss://remote-browser.example.com/cdp', 'CDP URL should be first arg'
			assert call_kwargs[1].get('additional_headers') == test_headers, 'Headers should be passed as additional_headers'
			assert call_kwargs[1].get('max_ws_frame_size') == 200 * 1024 * 1024, 'max_ws_frame_size should be set'


@pytest.mark.asyncio
async def test_cdp_client_no_headers_when_none():
	"""Test that CDPClient is created with None headers when profile has no headers."""
	session = BrowserSession(cdp_url='wss://example.com/cdp')

	assert session.browser_profile.headers is None

	with patch('browser_use.browser.session.CDPClient') as mock_cdp_client_class:
		mock_cdp_client = AsyncMock()
		mock_cdp_client_class.return_value = mock_cdp_client
		mock_cdp_client.start = AsyncMock()
		mock_cdp_client.stop = AsyncMock()
		mock_cdp_client.send = MagicMock()
		mock_cdp_client.send.Target = MagicMock()
		mock_cdp_client.send.Target.setAutoAttach = AsyncMock()
		mock_cdp_client.send.Target.getTargets = AsyncMock(return_value={'targetInfos': []})
		mock_cdp_client.send.Target.createTarget = AsyncMock(return_value={'targetId': 'test-target-id'})

		with patch('browser_use.browser.session_manager.SessionManager') as mock_session_manager_class:
			mock_session_manager = MagicMock()
			mock_session_manager_class.return_value = mock_session_manager
			mock_session_manager.start_monitoring = AsyncMock()
			mock_session_manager.get_all_page_targets = MagicMock(return_value=[])

			try:
				await session.connect()
			except Exception:
				pass

			# Verify CDPClient was called with None for additional_headers
			call_kwargs = mock_cdp_client_class.call_args
			assert call_kwargs[1].get('additional_headers') is None


@pytest.mark.asyncio
async def test_headers_used_for_json_version_endpoint():
	"""Test that headers are also used when fetching WebSocket URL from /json/version."""
	test_headers = {'Authorization': 'Bearer test-token'}

	# Use HTTP URL (not ws://) to trigger /json/version fetch
	session = BrowserSession(cdp_url='http://remote-browser.example.com:9222', headers=test_headers)

	with patch('browser_use.browser.session.httpx.AsyncClient') as mock_client_class:
		mock_client = AsyncMock()
		mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
		mock_client_class.return_value.__aexit__ = AsyncMock()

		# Mock the /json/version response
		mock_response = MagicMock()
		mock_response.json.return_value = {'webSocketDebuggerUrl': 'ws://remote-browser.example.com:9222/devtools/browser/abc'}
		mock_client.get = AsyncMock(return_value=mock_response)

		with patch('browser_use.browser.session.CDPClient') as mock_cdp_client_class:
			mock_cdp_client = AsyncMock()
			mock_cdp_client_class.return_value = mock_cdp_client
			mock_cdp_client.start = AsyncMock()
			mock_cdp_client.send = MagicMock()
			mock_cdp_client.send.Target = MagicMock()
			mock_cdp_client.send.Target.setAutoAttach = AsyncMock()

			with patch('browser_use.browser.session_manager.SessionManager') as mock_sm_class:
				mock_sm = MagicMock()
				mock_sm_class.return_value = mock_sm
				mock_sm.start_monitoring = AsyncMock()
				mock_sm.get_all_page_targets = MagicMock(return_value=[])

				try:
					await session.connect()
				except Exception:
					pass

				# Verify headers were passed to the HTTP GET request
				mock_client.get.assert_called_once()
				call_kwargs = mock_client.get.call_args
				assert call_kwargs[1].get('headers') == test_headers
