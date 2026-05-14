"""Tests for cloud browser functionality."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from browser_use.browser.cloud.cloud import (
	CloudBrowserAuthError,
	CloudBrowserClient,
	CloudBrowserError,
)
from browser_use.browser.cloud.views import CloudBrowserResponse, CreateBrowserRequest
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.sync.auth import CloudAuthConfig


@pytest.fixture
def temp_config_dir(monkeypatch):
	"""Create temporary config directory."""
	with tempfile.TemporaryDirectory() as tmpdir:
		temp_dir = Path(tmpdir) / '.config' / 'browseruse'
		temp_dir.mkdir(parents=True, exist_ok=True)

		# Use monkeypatch to set the environment variable
		monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(temp_dir))

		yield temp_dir


@pytest.fixture
def mock_auth_config(temp_config_dir):
	"""Create a mock auth config with valid token."""
	auth_config = CloudAuthConfig(api_token='test-token', user_id='test-user-id', authorized_at=None)
	auth_config.save_to_file()
	return auth_config


class TestCloudBrowserClient:
	"""Test CloudBrowserClient class."""

	async def test_create_browser_success(self, mock_auth_config, monkeypatch):
		"""Test successful cloud browser creation."""

		# Clear environment variable so test uses mock_auth_config
		monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)

		# Mock response data matching the API
		mock_response_data = {
			'id': 'test-browser-id',
			'status': 'active',
			'liveUrl': 'https://live.browser-use.com?wss=test',
			'cdpUrl': 'wss://test.proxy.daytona.works',
			'timeoutAt': '2025-09-17T04:35:36.049892',
			'startedAt': '2025-09-17T03:35:36.049974',
			'finishedAt': None,
		}

		# Mock the httpx client
		with patch('httpx.AsyncClient') as mock_client_class:
			mock_response = AsyncMock()
			mock_response.status_code = 201
			mock_response.is_success = True
			mock_response.json = lambda: mock_response_data

			mock_client = AsyncMock()
			mock_client.post.return_value = mock_response
			mock_client_class.return_value = mock_client

			client = CloudBrowserClient()
			client.client = mock_client

			result = await client.create_browser(CreateBrowserRequest())

			assert result.id == 'test-browser-id'
			assert result.status == 'active'
			assert result.cdpUrl == 'wss://test.proxy.daytona.works'

			# Verify auth headers were included
			mock_client.post.assert_called_once()
			call_args = mock_client.post.call_args
			assert 'X-Browser-Use-API-Key' in call_args.kwargs['headers']
			assert call_args.kwargs['headers']['X-Browser-Use-API-Key'] == 'test-token'

	async def test_create_browser_auth_error(self, temp_config_dir, monkeypatch):
		"""Test cloud browser creation with auth error."""

		# Clear environment variable and don't create auth config - should trigger auth error
		monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)

		client = CloudBrowserClient()

		with pytest.raises(CloudBrowserAuthError) as exc_info:
			await client.create_browser(CreateBrowserRequest())

		assert 'BROWSER_USE_API_KEY is not set' in str(exc_info.value)

	async def test_create_browser_http_401(self, mock_auth_config, monkeypatch):
		"""Test cloud browser creation with HTTP 401 response."""

		# Clear environment variable so test uses mock_auth_config
		monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)

		with patch('httpx.AsyncClient') as mock_client_class:
			mock_response = AsyncMock()
			mock_response.status_code = 401
			mock_response.is_success = False

			mock_client = AsyncMock()
			mock_client.post.return_value = mock_response
			mock_client_class.return_value = mock_client

			client = CloudBrowserClient()
			client.client = mock_client

			with pytest.raises(CloudBrowserAuthError) as exc_info:
				await client.create_browser(CreateBrowserRequest())

			assert 'BROWSER_USE_API_KEY is invalid' in str(exc_info.value)

	async def test_create_browser_with_env_var(self, temp_config_dir, monkeypatch):
		"""Test cloud browser creation using BROWSER_USE_API_KEY environment variable."""

		# Set environment variable
		monkeypatch.setenv('BROWSER_USE_API_KEY', 'env-test-token')

		# Mock response data matching the API
		mock_response_data = {
			'id': 'test-browser-id',
			'status': 'active',
			'liveUrl': 'https://live.browser-use.com?wss=test',
			'cdpUrl': 'wss://test.proxy.daytona.works',
			'timeoutAt': '2025-09-17T04:35:36.049892',
			'startedAt': '2025-09-17T03:35:36.049974',
			'finishedAt': None,
		}

		with patch('httpx.AsyncClient') as mock_client_class:
			mock_response = AsyncMock()
			mock_response.status_code = 201
			mock_response.is_success = True
			mock_response.json = lambda: mock_response_data

			mock_client = AsyncMock()
			mock_client.post.return_value = mock_response
			mock_client_class.return_value = mock_client

			client = CloudBrowserClient()
			client.client = mock_client

			result = await client.create_browser(CreateBrowserRequest())

			assert result.id == 'test-browser-id'
			assert result.status == 'active'
			assert result.cdpUrl == 'wss://test.proxy.daytona.works'

			# Verify environment variable was used
			mock_client.post.assert_called_once()
			call_args = mock_client.post.call_args
			assert 'X-Browser-Use-API-Key' in call_args.kwargs['headers']
			assert call_args.kwargs['headers']['X-Browser-Use-API-Key'] == 'env-test-token'

	async def test_stop_browser_success(self, mock_auth_config, monkeypatch):
		"""Test successful cloud browser session stop."""

		# Clear environment variable so test uses mock_auth_config
		monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)

		# Mock response data for stop
		mock_response_data = {
			'id': 'test-browser-id',
			'status': 'stopped',
			'liveUrl': 'https://live.browser-use.com?wss=test',
			'cdpUrl': 'wss://test.proxy.daytona.works',
			'timeoutAt': '2025-09-17T04:35:36.049892',
			'startedAt': '2025-09-17T03:35:36.049974',
			'finishedAt': '2025-09-17T04:35:36.049892',
		}

		with patch('httpx.AsyncClient') as mock_client_class:
			mock_response = AsyncMock()
			mock_response.status_code = 200
			mock_response.is_success = True
			mock_response.json = lambda: mock_response_data

			mock_client = AsyncMock()
			mock_client.patch.return_value = mock_response
			mock_client_class.return_value = mock_client

			client = CloudBrowserClient()
			client.client = mock_client
			client.current_session_id = 'test-browser-id'

			result = await client.stop_browser()

			assert result.id == 'test-browser-id'
			assert result.status == 'stopped'
			assert result.finishedAt is not None

			# Verify correct API call
			mock_client.patch.assert_called_once()
			call_args = mock_client.patch.call_args
			assert 'test-browser-id' in call_args.args[0]  # URL contains session ID
			assert call_args.kwargs['json'] == {'action': 'stop'}
			assert 'X-Browser-Use-API-Key' in call_args.kwargs['headers']

	async def test_stop_browser_session_not_found(self, mock_auth_config, monkeypatch):
		"""Test stopping a browser session that doesn't exist."""

		# Clear environment variable so test uses mock_auth_config
		monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)

		with patch('httpx.AsyncClient') as mock_client_class:
			mock_response = AsyncMock()
			mock_response.status_code = 404
			mock_response.is_success = False

			mock_client = AsyncMock()
			mock_client.patch.return_value = mock_response
			mock_client_class.return_value = mock_client

			client = CloudBrowserClient()
			client.client = mock_client

			with pytest.raises(CloudBrowserError) as exc_info:
				await client.stop_browser('nonexistent-session')

			assert 'not found' in str(exc_info.value)

	async def test_get_browser_success(self, mock_auth_config, monkeypatch):
		"""Test fetching cloud browser details."""

		monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)

		mock_response_data = {
			'id': 'test-browser-id',
			'status': 'active',
			'liveUrl': 'https://live.browser-use.com?wss=test',
			'cdpUrl': 'wss://fresh.proxy.browser-use.com/devtools/browser/test',
			'timeoutAt': '2025-09-17T04:35:36.049892',
			'startedAt': '2025-09-17T03:35:36.049974',
			'finishedAt': None,
		}

		with patch('httpx.AsyncClient') as mock_client_class:
			mock_response = AsyncMock()
			mock_response.status_code = 200
			mock_response.is_success = True
			mock_response.json = lambda: mock_response_data

			mock_client = AsyncMock()
			mock_client.get.return_value = mock_response
			mock_client_class.return_value = mock_client

			client = CloudBrowserClient()
			client.client = mock_client
			client.current_session_id = 'test-browser-id'

			result = await client.get_browser()

			assert result.id == 'test-browser-id'
			assert result.cdpUrl == 'wss://fresh.proxy.browser-use.com/devtools/browser/test'

			mock_client.get.assert_called_once()
			call_args = mock_client.get.call_args
			assert 'X-Browser-Use-API-Key' in call_args.kwargs['headers']
			assert call_args.kwargs['headers']['X-Browser-Use-API-Key'] == 'test-token'


class TestBrowserSessionCloudIntegration:
	"""Test BrowserSession integration with cloud browsers."""

	async def test_cloud_browser_profile_property(self):
		"""Test that cloud_browser property works correctly."""

		# Just test the profile and session properties without connecting
		profile = BrowserProfile(use_cloud=True)
		session = BrowserSession(browser_profile=profile, cdp_url='ws://mock-url')  # Provide CDP URL to avoid connection

		assert session.cloud_browser is True
		assert session.browser_profile.use_cloud is True

	async def test_browser_session_cloud_browser_logic(self, mock_auth_config, monkeypatch):
		"""Test that cloud browser profile settings work correctly."""

		# Clear environment variable so test uses mock_auth_config
		monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)

		# Test cloud browser profile creation
		profile = BrowserProfile(use_cloud=True)
		assert profile.use_cloud is True

		# Test that BrowserSession respects cloud_browser setting
		# Provide CDP URL to avoid actual connection attempts
		session = BrowserSession(browser_profile=profile, cdp_url='ws://mock-url')
		assert session.cloud_browser is True

	async def test_reconnect_refreshes_cloud_cdp_url(self, mock_auth_config, monkeypatch):
		"""Reconnect should refresh cloud cdp_url before rebuilding the CDP client."""

		monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)

		cloud_session_id = '7166c636-8500-4bb7-afd9-31bc025dc630'
		old_cdp_url = f'wss://{cloud_session_id}.cdp1.browser-use.com/devtools/browser/old'
		fresh_cdp_url = f'wss://{cloud_session_id}.cdp2.browser-use.com/devtools/browser/fresh'

		session = BrowserSession(browser_profile=BrowserProfile(use_cloud=True), cdp_url=old_cdp_url)
		session.browser_profile.is_local = False
		session._cloud_browser_client.current_session_id = cloud_session_id
		session.agent_focus_target_id = 'target-123'
		session._cloud_browser_client.get_browser = AsyncMock(
			return_value=CloudBrowserResponse(
				id=cloud_session_id,
				status='active',
				liveUrl='https://live.browser-use.com?wss=test',
				cdpUrl=fresh_cdp_url,
				timeoutAt='2025-09-17T04:35:36.049892',
				startedAt='2025-09-17T03:35:36.049974',
				finishedAt=None,
			)
		)

		old_root_client = Mock()
		old_root_client.stop = AsyncMock()
		session._cdp_client_root = old_root_client

		old_session_manager = Mock()
		old_session_manager.clear = AsyncMock()
		session.session_manager = old_session_manager

		new_root_client = Mock()
		new_root_client.start = AsyncMock()
		new_root_client.send = Mock()
		new_root_client.send.Target = Mock()
		new_root_client.send.Target.setAutoAttach = AsyncMock()

		new_session_manager = Mock()
		new_session_manager.start_monitoring = AsyncMock()
		new_session_manager.get_all_page_targets.return_value = [Mock(target_id='target-123')]

		with (
			patch('browser_use.browser.session.CDPClient', return_value=new_root_client) as mock_cdp_client,
			patch('browser_use.browser.session_manager.SessionManager', return_value=new_session_manager),
			patch.object(BrowserSession, 'get_or_create_cdp_session', AsyncMock()) as mock_get_or_create,
			patch.object(BrowserSession, '_setup_proxy_auth', AsyncMock()),
			patch.object(BrowserSession, '_attach_ws_drop_callback'),
		):
			await session.reconnect()

		session._cloud_browser_client.get_browser.assert_awaited_once_with(cloud_session_id)
		assert session.cdp_url == fresh_cdp_url
		assert mock_cdp_client.call_args.args[0] == fresh_cdp_url
		old_root_client.stop.assert_awaited_once()
		old_session_manager.clear.assert_awaited_once()
		new_session_manager.start_monitoring.assert_awaited_once()
		new_root_client.start.assert_awaited_once()
		new_root_client.send.Target.setAutoAttach.assert_awaited_once()
		mock_get_or_create.assert_awaited_once_with('target-123', focus=True)
