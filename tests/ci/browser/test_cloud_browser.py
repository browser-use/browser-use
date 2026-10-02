"""Tests for cloud browser functionality."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from browser_use.browser.cloud.cloud import (
	CloudBrowserAuthError,
	CloudBrowserClient,
	CloudBrowserError,
)
from browser_use.browser.cloud.views import CreateBrowserRequest
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
			mock_client.request.return_value = mock_response
			mock_client_class.return_value = mock_client

			client = CloudBrowserClient()
			client.client = mock_client

			result = await client.create_browser(CreateBrowserRequest())

			assert result.id == 'test-browser-id'
			assert result.status == 'active'
			assert result.cdpUrl == 'wss://test.proxy.daytona.works'

			# Verify auth headers were included
			mock_client.request.assert_called_once()
			call_args = mock_client.request.call_args
			assert call_args.args[:2] == ('POST', 'https://api.browser-use.com/api/v2/browsers')
			assert 'X-Browser-Use-API-Key' in call_args.kwargs['headers']
			assert call_args.kwargs['headers']['X-Browser-Use-API-Key'] == 'test-token'
			assert client.current_api_version == 'v2'

	async def test_create_browser_falls_through_version_scopes(self, mock_auth_config, monkeypatch):
		monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)
		missing_scope = AsyncMock()
		missing_scope.status_code = 403
		missing_scope.is_success = False
		missing_scope.json = lambda: {'detail': 'API key is missing required scope: v2:browsers:create'}
		created = AsyncMock()
		created.status_code = 201
		created.is_success = True
		created.json = lambda: {
			'id': 'test-browser-id',
			'status': 'active',
			'liveUrl': 'https://live.browser-use.com?wss=test',
			'cdpUrl': 'wss://test.proxy.daytona.works',
			'timeoutAt': '2025-09-17T04:35:36.049892',
			'startedAt': '2025-09-17T03:35:36.049974',
			'finishedAt': None,
		}

		with patch('httpx.AsyncClient') as mock_client_class:
			mock_client = AsyncMock()
			mock_client.request.side_effect = [missing_scope, created]
			mock_client_class.return_value = mock_client
			client = CloudBrowserClient()
			client.client = mock_client

			result = await client.create_browser(CreateBrowserRequest())

			assert result.id == 'test-browser-id'
			assert [call.args[:2] for call in mock_client.request.call_args_list] == [
				('POST', 'https://api.browser-use.com/api/v2/browsers'),
				('POST', 'https://api.browser-use.com/api/v3/browsers'),
			]
			assert client.current_api_version == 'v3'

			stopped = AsyncMock()
			stopped.status_code = 200
			stopped.is_success = True
			stopped.json = lambda: {**created.json(), 'status': 'stopped', 'liveUrl': None, 'cdpUrl': None}
			mock_client.request.side_effect = [stopped]
			await client.stop_browser()
			assert mock_client.request.call_args.args[:2] == (
				'PATCH',
				'https://api.browser-use.com/api/v3/browsers/test-browser-id',
			)
			assert client.current_session_id is None
			assert client.current_api_version is None

	async def test_create_browser_renegotiates_for_a_new_scoped_key(self, mock_auth_config, monkeypatch):
		monkeypatch.setenv('BROWSER_USE_API_KEY', 'new-v2-key')
		with patch('httpx.AsyncClient') as mock_client_class:
			response = AsyncMock()
			response.status_code = 201
			response.is_success = True
			response.json = lambda: {
				'id': 'new-browser',
				'status': 'active',
				'liveUrl': None,
				'cdpUrl': 'wss://example.invalid',
				'timeoutAt': '2025-09-17T04:35:36',
				'startedAt': '2025-09-17T03:35:36',
				'finishedAt': None,
			}
			mock_client_class.return_value = AsyncMock()
			mock_client_class.return_value.request.return_value = response
			client = CloudBrowserClient()
			client.current_api_version = 'v3'
			await client.create_browser(CreateBrowserRequest())
			assert mock_client_class.return_value.request.call_args.args[:2] == (
				'POST',
				'https://api.browser-use.com/api/v2/browsers',
			)
			assert mock_client_class.return_value.request.call_args.kwargs['headers']['X-Browser-Use-API-Key'] == 'new-v2-key'
			assert client.current_api_version == 'v2'

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
			mock_client.request.return_value = mock_response
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
			mock_client.request.return_value = mock_response
			mock_client_class.return_value = mock_client

			client = CloudBrowserClient()
			client.client = mock_client

			result = await client.create_browser(CreateBrowserRequest())

			assert result.id == 'test-browser-id'
			assert result.status == 'active'
			assert result.cdpUrl == 'wss://test.proxy.daytona.works'

			# Verify environment variable was used
			mock_client.request.assert_called_once()
			call_args = mock_client.request.call_args
			assert call_args.args[0] == 'POST'
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
			'liveUrl': None,
			'cdpUrl': None,
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
			mock_client.request.return_value = mock_response
			mock_client_class.return_value = mock_client

			client = CloudBrowserClient()
			client.client = mock_client
			client.current_session_id = 'test-browser-id'

			result = await client.stop_browser()

			assert result.id == 'test-browser-id'
			assert result.status == 'stopped'
			assert result.liveUrl is None
			assert result.cdpUrl is None
			assert result.finishedAt is not None

			# Verify correct API call
			mock_client.request.assert_called_once()
			call_args = mock_client.request.call_args
			assert call_args.args[:2] == (
				'PATCH',
				'https://api.browser-use.com/api/v2/browsers/test-browser-id',
			)
			assert call_args.kwargs['json'] == {'action': 'stop'}
			assert 'X-Browser-Use-API-Key' in call_args.kwargs['headers']
			assert client.current_api_version is None

	async def test_stop_browser_session_not_found(self, mock_auth_config, monkeypatch):
		"""Test stopping a browser session that doesn't exist."""

		# Clear environment variable so test uses mock_auth_config
		monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)

		with patch('httpx.AsyncClient') as mock_client_class:
			mock_response = AsyncMock()
			mock_response.status_code = 404
			mock_response.is_success = False

			mock_client = AsyncMock()
			mock_client.request.return_value = mock_response
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
