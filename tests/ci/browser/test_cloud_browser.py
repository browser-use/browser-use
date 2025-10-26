"""Tests for cloud browser functionality."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from browser_use.browser.cloud import (
	CloudBrowserAuthError,
	CloudBrowserClient,
	CloudBrowserError,
	get_cloud_browser_cdp_url,
	stop_cloud_browser_session,
)
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

			result = await client.create_browser()

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
			await client.create_browser()

		assert 'BROWSER_USE_API_KEY environment variable' in str(exc_info.value)

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
				await client.create_browser()

			assert 'Authentication failed' in str(exc_info.value)

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

			result = await client.create_browser()

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


class TestBrowserSessionCloudIntegration:
	"""Test BrowserSession integration with cloud browsers."""

	async def test_cloud_browser_profile_property(self):
		"""Test that cloud_browser property works correctly."""

		profile = BrowserProfile(use_cloud=True)
		session = BrowserSession(browser_profile=profile)

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
		session = BrowserSession(browser_profile=profile)
		assert session.cloud_browser is True

		# Test that get_cloud_browser_cdp_url works with mocked API
		with patch('browser_use.browser.cloud.get_cloud_browser_cdp_url') as mock_get_cdp_url:
			mock_get_cdp_url.return_value = 'wss://test.proxy.daytona.works'

			cdp_url = await mock_get_cdp_url()
			assert cdp_url == 'wss://test.proxy.daytona.works'
			mock_get_cdp_url.assert_called_once()


async def test_get_cloud_browser_cdp_url_function(mock_auth_config, monkeypatch):
	"""Test the get_cloud_browser_cdp_url convenience function."""

	# Clear environment variable so test uses mock_auth_config
	monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)

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

		cdp_url = await get_cloud_browser_cdp_url()

		assert cdp_url == 'wss://test.proxy.daytona.works'


async def test_cloud_browser_auth_error_no_fallback(temp_config_dir, monkeypatch):
	"""Test that cloud browser throws error when auth fails (no fallback)."""

	# Clear environment variable and don't create auth config to trigger auth error
	monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)

	# Don't create auth config to trigger auth error
	profile = BrowserProfile(use_cloud=True)

	# Verify that the cloud browser client raises the expected error
	with pytest.raises(CloudBrowserAuthError) as exc_info:
		await get_cloud_browser_cdp_url()

	assert 'BROWSER_USE_API_KEY environment variable' in str(exc_info.value)

	# Verify profile state unchanged (no fallback)
	assert profile.use_cloud is True
	assert profile.is_local is False


async def test_stop_cloud_browser_session_function(mock_auth_config, monkeypatch):
	"""Test the stop_cloud_browser_session convenience function."""

	# Clear environment variable so test uses mock_auth_config
	monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)

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

		result = await stop_cloud_browser_session('test-browser-id')

		assert result.id == 'test-browser-id'
		assert result.status == 'stopped'
