"""
Tests for OAuth2 device flow and cloud sync functionality.
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import anyio
import httpx
import pytest
from dotenv import load_dotenv
from pytest_httpserver import HTTPServer

# Load environment variables before any imports
load_dotenv()


from browser_use.agent.cloud_events import CreateAgentSessionEvent, CreateAgentTaskEvent
from browser_use.sync.auth import TEMP_USER_ID, DeviceAuthClient
from browser_use.sync.service import CloudSync

# Define config dir for tests - not needed anymore since we'll use env vars


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
async def http_client(httpserver: HTTPServer):
	"""Create a real HTTP client pointed at the test server"""
	async with httpx.AsyncClient(base_url=httpserver.url_for('')) as client:
		yield client


class TestDeviceAuthClient:
	"""Test DeviceAuthClient class."""

	async def test_init_creates_config_dir(self, temp_config_dir, httpserver):
		"""Test that initialization creates config directory."""
		auth = DeviceAuthClient(base_url=httpserver.url_for(''))
		assert temp_config_dir.exists()
		assert (temp_config_dir / 'cloud_auth.json').exists() is False

	async def test_load_credentials_no_file(self, temp_config_dir, httpserver):
		"""Test loading credentials when file doesn't exist."""
		auth = DeviceAuthClient(base_url=httpserver.url_for(''))
		# When no file exists, auth_config should have no token/user_id
		assert auth.auth_config.api_token is None
		assert auth.auth_config.user_id is None
		assert not auth.is_authenticated

	async def test_save_and_load_credentials(self, temp_config_dir, httpserver):
		"""Test saving and loading credentials."""
		auth = DeviceAuthClient(base_url=httpserver.url_for(''))

		# Update auth config and save
		auth.auth_config.api_token = 'test-key-123'
		auth.auth_config.user_id = 'test-user-123'
		auth.auth_config.authorized_at = datetime.utcnow()
		auth.auth_config.save_to_file()

		# Load in a new instance
		auth2 = DeviceAuthClient(base_url=httpserver.url_for(''))
		assert auth2.auth_config.api_token == 'test-key-123'
		assert auth2.auth_config.user_id == 'test-user-123'
		assert auth2.is_authenticated
		assert (temp_config_dir / 'cloud_auth.json').exists()

		# Check file permissions (should be readable only by owner)
		stat = (temp_config_dir / 'cloud_auth.json').stat()
		assert oct(stat.st_mode)[-3:] == '600'

	async def test_is_authenticated(self, temp_config_dir, httpserver):
		"""Test authentication status check."""
		auth = DeviceAuthClient(base_url=httpserver.url_for(''))

		# Not authenticated initially
		assert auth.is_authenticated is False

		# Save credentials
		auth.auth_config.api_token = 'test-key'
		auth.auth_config.user_id = 'test-user'
		auth.auth_config.save_to_file()

		# Reload to verify persistence
		auth2 = DeviceAuthClient(base_url=httpserver.url_for(''))
		assert auth2.is_authenticated is True

	async def test_get_credentials(self, temp_config_dir, httpserver):
		"""Test getting credentials."""
		auth = DeviceAuthClient(base_url=httpserver.url_for(''))

		# No credentials initially
		assert auth.api_token is None
		assert auth.user_id == TEMP_USER_ID  # Should return temp user ID when not authenticated

		# Save credentials
		auth.auth_config.api_token = 'test-key'
		auth.auth_config.user_id = 'test-user'

		# Get credentials
		assert auth.api_token == 'test-key'
		assert auth.user_id == 'test-user'

	async def test_start_device_flow(self, httpserver: HTTPServer, http_client, temp_config_dir):
		"""Test starting device flow."""
		# Set up the test server response
		httpserver.expect_request(
			'/api/v1/oauth/device/authorize',
			method='POST',
		).respond_with_json(
			{
				'device_code': 'test-device-code',
				'user_code': 'ABCD-1234',
				'verification_uri': 'https://example.com/device',
				'verification_uri_complete': 'https://example.com/device?user_code=ABCD-1234',
				'expires_in': 1800,
				'interval': 5,
			}
		)

		# Create auth client with injected http client
		auth = DeviceAuthClient(base_url=httpserver.url_for(''), http_client=http_client)
		result = await auth.start_device_authorization('test-session-id')

		assert result['device_code'] == 'test-device-code'
		assert result['user_code'] == 'ABCD-1234'
		assert 'verification_uri' in result

		# Verify the request was made correctly
		request = httpserver.log[0][0]
		assert request.method == 'POST'
		# Get the body as string
		body = request.get_data(as_text=True)
		assert 'client_id=library' in body
		assert 'agent_session_id=test-session-id' in body
		assert 'device_id=' in body  # Should include device_id

	async def test_poll_for_token_pending(self, httpserver: HTTPServer, http_client, temp_config_dir):
		"""Test polling when authorization is pending."""
		# Set up the test server to always return pending
		httpserver.expect_request(
			'/api/v1/oauth/device/token',
			method='POST',
		).respond_with_json(
			{
				'error': 'authorization_pending',
				'error_description': 'Authorization pending',
			}
		)

		auth = DeviceAuthClient(base_url=httpserver.url_for(''), http_client=http_client)
		# Use very short timeout to avoid long test
		result = await auth.poll_for_token('test-device-code', interval=0.1, timeout=0.5)

		assert result is None
		assert not auth.is_authenticated

	async def test_poll_for_token_success(self, httpserver: HTTPServer, http_client, temp_config_dir):
		"""Test successful token polling."""
		# Set up the test server to return success immediately
		httpserver.expect_request(
			'/api/v1/oauth/device/token',
			method='POST',
		).respond_with_json(
			{
				'access_token': 'test-api-key',
				'token_type': 'Bearer',
				'user_id': 'test-user-123',
				'scope': 'read write',
			}
		)

		auth = DeviceAuthClient(base_url=httpserver.url_for(''), http_client=http_client)
		result = await auth.poll_for_token('test-device-code')

		assert result is not None
		assert result['access_token'] == 'test-api-key'
		assert result['user_id'] == 'test-user-123'

	async def test_wait_for_authorization(self, httpserver: HTTPServer, http_client, temp_config_dir):
		"""Test waiting for authorization with polling."""
		# Track number of requests
		request_count = 0

		def handle_token_request(request):
			nonlocal request_count
			request_count += 1

			from werkzeug.wrappers import Response

			if request_count < 3:
				# First two requests return pending
				return Response(
					json.dumps({'error': 'authorization_pending', 'error_description': 'Authorization pending'}),
					status=200,
					mimetype='application/json',
				)
			else:
				# Third request returns success
				return Response(
					json.dumps(
						{
							'access_token': 'test-api-key',
							'token_type': 'Bearer',
							'user_id': 'test-user-123',
							'scope': 'read write',
						}
					),
					status=200,
					mimetype='application/json',
				)

		# Set up auth endpoint
		httpserver.expect_request(
			'/api/v1/oauth/device/authorize',
			method='POST',
		).respond_with_json(
			{
				'device_code': 'test-device-code',
				'user_code': 'ABCD-1234',
				'verification_uri': 'https://example.com/device',
				'verification_uri_complete': 'https://example.com/device?user_code=ABCD-1234',
				'expires_in': 1800,
				'interval': 0.1,  # Short interval for testing
			}
		)

		# Set up token endpoint with custom handler
		httpserver.expect_request(
			'/api/v1/oauth/device/token',
			method='POST',
		).respond_with_handler(handle_token_request)

		auth = DeviceAuthClient(base_url=httpserver.url_for(''), http_client=http_client)
		success = await auth.authenticate(agent_session_id='test-session-id', show_instructions=False)

		assert success is True
		assert auth.is_authenticated
		assert auth.api_token == 'test-api-key'
		assert auth.user_id == 'test-user-123'
		assert request_count == 3  # Verify it took 3 polls

	async def test_wait_for_authorization_timeout(self, httpserver: HTTPServer, http_client, temp_config_dir):
		"""Test timeout during authorization waiting."""
		# Set up auth endpoint
		httpserver.expect_request(
			'/api/v1/oauth/device/authorize',
			method='POST',
		).respond_with_json(
			{
				'device_code': 'test-device-code',
				'user_code': 'ABCD-1234',
				'verification_uri': 'https://example.com/device',
				'verification_uri_complete': 'https://example.com/device?user_code=ABCD-1234',
				'expires_in': 1800,
				'interval': 0.1,
			}
		)

		# Set up token endpoint to always return pending
		httpserver.expect_request(
			'/api/v1/oauth/device/token',
			method='POST',
		).respond_with_json(
			{
				'error': 'authorization_pending',
				'error_description': 'Authorization pending',
			}
		)

		auth = DeviceAuthClient(base_url=httpserver.url_for(''), http_client=http_client)

		# Call poll_for_token directly with short timeout
		result = await auth.poll_for_token('test-device-code', interval=0.1, timeout=0.5)
		assert result is None  # Should timeout and return None
		assert not auth.is_authenticated

	async def test_logout(self, temp_config_dir, httpserver):
		"""Test logout functionality."""
		auth = DeviceAuthClient(base_url=httpserver.url_for(''))

		# Save credentials directly using auth_config
		auth.auth_config.api_token = 'test-key'
		auth.auth_config.user_id = 'test-user'
		auth.auth_config.save_to_file()

		assert auth.is_authenticated is True
		assert (temp_config_dir / 'cloud_auth.json').exists()

		# Clear auth (logout)
		auth.clear_auth()

		assert auth.is_authenticated is False
		# Note: clear_auth() saves an empty config, so file still exists
		assert (temp_config_dir / 'cloud_auth.json').exists()

		# Verify the file contains empty credentials
		auth2 = DeviceAuthClient(base_url=httpserver.url_for(''))
		assert auth2.auth_config.api_token is None
		assert auth2.auth_config.user_id is None


class TestCloudSync:
	"""Test CloudSync class."""

	async def test_init(self, temp_config_dir, httpserver):
		"""Test CloudSync initialization."""
		service = CloudSync(
			base_url=httpserver.url_for(''),
			enable_auth=True,
		)

		assert service.base_url == httpserver.url_for('')
		assert service.enable_auth is True
		assert service.auth_client is not None
		assert isinstance(service.auth_client, DeviceAuthClient)
		assert service.pending_events == []

	async def test_send_event_authenticated(self, httpserver: HTTPServer, temp_config_dir):
		"""Test sending event when authenticated."""
		requests = []

		def capture_request(request):
			requests.append(
				{
					'headers': dict(request.headers),
					'json': request.get_json(),
				}
			)
			from werkzeug.wrappers import Response

			return Response('{"processed": 1, "failed": 0}', status=200, mimetype='application/json')

		httpserver.expect_request('/api/v1/events', method='POST').respond_with_handler(capture_request)

		# Create authenticated service
		auth = DeviceAuthClient(base_url=httpserver.url_for(''))
		auth.auth_config.api_token = 'test-api-key'
		auth.auth_config.user_id = 'test-user-123'

		service = CloudSync(base_url=httpserver.url_for(''), enable_auth=True)
		service.auth_client = auth
		service.session_id = 'test-session-id'

		# Send event
		await service.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Test task',
				user_id='test-user-123',
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
				device_id='test-device-id',
			)
		)

		# Check request was made
		assert len(requests) == 1
		request_data = requests[0]

		# Check auth header
		assert request_data['headers']['Authorization'] == 'Bearer test-api-key'

		# Check event data
		json_data = request_data['json']
		assert len(json_data['events']) == 1
		event = json_data['events'][0]
		assert event['event_type'] == 'CreateAgentTaskEvent'
		assert event['user_id'] == 'test-user-123'
		assert event['task'] == 'Test task'

	async def test_send_event_pre_auth(self, httpserver: HTTPServer, temp_config_dir):
		"""Test sending event before authentication."""
		requests = []

		def capture_request(request):
			requests.append(
				{
					'headers': dict(request.headers),
					'json': request.get_json(),
				}
			)
			from werkzeug.wrappers import Response

			return Response('{"processed": 1, "failed": 0}', status=200, mimetype='application/json')

		httpserver.expect_request('/api/v1/events', method='POST').respond_with_handler(capture_request)

		# Create unauthenticated service
		auth = DeviceAuthClient(base_url=httpserver.url_for(''))
		# Don't set api_token - leave it unauthenticated

		service = CloudSync(base_url=httpserver.url_for(''), enable_auth=True)
		service.auth_client = auth
		service.session_id = 'test-session-id'

		# Send event
		await service.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Test task',
				user_id=TEMP_USER_ID,
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
				device_id='test-device-id',
			)
		)

		# Check request was made without auth header
		assert len(requests) == 1
		request_data = requests[0]
		assert 'Authorization' not in request_data['headers']

		# Check event was sent with temp user ID
		json_data = request_data['json']
		assert len(json_data['events']) == 1
		event = json_data['events'][0]
		assert event['event_type'] == 'CreateAgentTaskEvent'
		assert event['user_id'] == TEMP_USER_ID
		assert event['task'] == 'Test task'

	async def test_authenticate_and_resend(self, httpserver: HTTPServer, temp_config_dir):
		"""Test authentication flow with pre-auth event resending."""
		requests = []
		request_count = 0

		def handle_events_request(request):
			nonlocal request_count
			request_count += 1
			requests.append(
				{
					'headers': dict(request.headers),
					'json': request.get_json(),
				}
			)

			from werkzeug.wrappers import Response

			if request_count == 1:
				# First request: unauthenticated, return 401
				return Response('{"error": "unauthorized"}', status=401, mimetype='application/json')
			else:
				# Subsequent requests: success
				return Response('{"processed": 1, "failed": 0}', status=200, mimetype='application/json')

		httpserver.expect_request('/api/v1/events', method='POST').respond_with_handler(handle_events_request)

		# Create service with unauthenticated auth client
		auth = DeviceAuthClient(base_url=httpserver.url_for(''))
		# Start unauthenticated

		service = CloudSync(base_url=httpserver.url_for(''), enable_auth=True)
		service.auth_client = auth
		service.session_id = 'test-session-id'

		# Send pre-auth event (should get 401 and be queued)
		await service.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Pre-auth task',
				user_id=TEMP_USER_ID,
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
				device_id='test-device-id',
			)
		)

		# Event should be in pending_events since we got 401
		assert len(service.pending_events) == 1
		assert hasattr(service.pending_events[0], 'task') and service.pending_events[0].task == 'Pre-auth task'  # type: ignore
		assert hasattr(service.pending_events[0], 'user_id') and service.pending_events[0].user_id == TEMP_USER_ID  # type: ignore

		# Now authenticate the auth client
		auth.auth_config.api_token = 'test-api-key'
		auth.auth_config.user_id = 'test-user-123'

		# Manually trigger resend of pending events
		await service._resend_pending_events()

		# Pre-auth events should be cleared after successful resend
		assert len(service.pending_events) == 0

		# Check that events were sent (1 original attempt + 1 resend)
		assert len(requests) == 2

		# Check first request was unauthenticated
		assert 'Authorization' not in requests[0]['headers']
		assert requests[0]['json']['events'][0]['user_id'] == TEMP_USER_ID

		# Check second request was authenticated with updated user_id
		assert requests[1]['headers']['Authorization'] == 'Bearer test-api-key'
		assert requests[1]['json']['events'][0]['user_id'] == 'test-user-123'

	async def test_error_handling(self, httpserver: HTTPServer, temp_config_dir):
		"""Test error handling during event sending."""
		# Set up server to return 500 error
		httpserver.expect_request('/api/v1/events', method='POST').respond_with_data('Internal Server Error', status=500)

		# Create service with real auth
		auth = DeviceAuthClient(base_url=httpserver.url_for(''))
		auth.auth_config.api_token = 'test-api-key'
		auth.auth_config.user_id = 'test-user-123'

		service = CloudSync(base_url=httpserver.url_for(''), enable_auth=True)
		service.auth_client = auth
		service.session_id = 'test-session-id'

		# Send event - should not raise exception but handle gracefully
		await service.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Test task',
				user_id='test-user-123',
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
				device_id='test-device-id',
			)
		)

		# Should handle error gracefully without crashing

	# async def test_update_wal_events(self, temp_config_dir):
	# 	"""Test updating WAL events with real user ID."""
	# 	# Create real auth client
	# 	auth = DeviceAuthClient(base_url='http://localhost:8000')
	# 	auth.auth_config.api_token = 'test-api-key'
	# 	auth.auth_config.user_id = 'test-user-123'

	# 	service = CloudSync(
	# 		base_url='http://localhost:8000',
	# 		enable_auth=True,
	# 	)
	# 	service.auth_client = auth
	# 	service.session_id = 'test-session-id'

	# 	# Create the events directory structure that the method expects
	# 	events_dir = temp_config_dir / 'events'
	# 	events_dir.mkdir(exist_ok=True)

	# 	# Create WAL file with temp user IDs
	# 	wal_path = events_dir / f'{service.session_id}.jsonl'
	# 	events = [
	# 		{
	# 			'event_type': 'CreateAgentTaskEvent',
	# 			'user_id': '99999999-9999-9999-9999-999999999999',  # TEMP_USER_ID
	# 			'task': 'Task 1',
	# 		},
	# 		{
	# 			'event_type': 'UpdateAgentTaskEvent',
	# 			'user_id': '99999999-9999-9999-9999-999999999999',  # TEMP_USER_ID
	# 			'status': 'done',
	# 		},
	# 		{
	# 			'event_type': 'CreateAgentStepEvent',
	# 			'user_id': 'some-other-user',  # Different user, should still be updated
	# 			'step': 1,
	# 		},
	# 	]

	# 	# Write events to WAL file
	# 	content = '\n'.join(json.dumps(event) for event in events) + '\n'
	# 	await anyio.Path(wal_path).write_text(content)

	# 	# Call the method under test (temp_config_dir fixture already sets the env var)
	# 	await service._update_wal_user_ids(service.session_id)

	# 	# Read back the updated file and verify changes
	# 	content = await anyio.Path(wal_path).read_text()

	# 	updated_events = []
	# 	for line in content.splitlines():
	# 		if line.strip():
	# 			updated_events.append(json.loads(line))

	# 	# Verify all user_ids were updated to the authenticated user's ID
	# 	assert len(updated_events) == 3
	# 	for event in updated_events:
	# 		assert event['user_id'] == 'test-user-123'

	# 	# Verify other fields remained unchanged
	# 	assert updated_events[0]['event_type'] == 'CreateAgentTaskEvent'
	# 	assert updated_events[0]['task'] == 'Task 1'
	# 	assert updated_events[1]['event_type'] == 'UpdateAgentTaskEvent'
	# 	assert updated_events[1]['status'] == 'done'
	# 	assert updated_events[2]['event_type'] == 'CreateAgentStepEvent'
	# 	assert updated_events[2]['step'] == 1


class TestIntegration:
	"""Integration tests for OAuth2 and cloud sync."""

	async def test_full_auth_flow(self, httpserver: HTTPServer, temp_config_dir):
		"""Test complete authentication flow."""
		# Track token polling attempts
		token_attempts = 0

		def handle_token_request(request):
			nonlocal token_attempts
			token_attempts += 1

			from werkzeug.wrappers import Response

			if token_attempts == 1:
				# First attempt: pending
				return Response(
					json.dumps({'error': 'authorization_pending'}),
					status=200,
					mimetype='application/json',
				)
			else:
				# Second attempt: success
				return Response(
					json.dumps(
						{
							'access_token': 'test-api-key',
							'token_type': 'Bearer',
							'user_id': 'test-user-123',
						}
					),
					status=200,
					mimetype='application/json',
				)

		# Set up auth flow endpoints
		httpserver.expect_request(
			'/api/v1/oauth/device/authorize',
			method='POST',
		).respond_with_json(
			{
				'device_code': 'test-device-code',
				'user_code': 'ABCD-1234',
				'verification_uri': f'{httpserver.url_for("")}/device',
				'verification_uri_complete': f'{httpserver.url_for("")}/device?user_code=ABCD-1234',
				'expires_in': 1800,
				'interval': 0.1,  # Fast polling for test
			}
		)

		httpserver.expect_request(
			'/api/v1/oauth/device/token',
			method='POST',
		).respond_with_handler(handle_token_request)

		# Set up events endpoint
		httpserver.expect_request(
			'/api/v1/events',
			method='POST',
		).respond_with_json({'processed': 1, 'failed': 0})

		# Create service
		service = CloudSync(base_url=httpserver.url_for(''), enable_auth=True)
		service.session_id = 'test-session-id'

		# Send pre-auth event
		await service.handle_event(
			CreateAgentSessionEvent(
				user_id=TEMP_USER_ID,
				browser_session_id='test-browser-session',
				browser_session_live_url='http://example.com/live',
				browser_session_cdp_url='ws://example.com/cdp',
				device_id='test-device-id',
			)
		)

		# Authenticate
		authenticated = await service.authenticate(show_instructions=False)
		assert authenticated is True
		assert service.auth_client is not None
		assert service.auth_client.is_authenticated
		assert service.auth_client.api_token == 'test-api-key'
		assert service.auth_client.user_id == 'test-user-123'

		# Send authenticated event
		await service.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Authenticated task',
				user_id='test-user-123',
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
				device_id='test-device-id',
			)
		)

		# Verify auth was saved
		auth_file = temp_config_dir / 'cloud_auth.json'
		assert await anyio.Path(auth_file).exists()

		content = await anyio.Path(auth_file).read_text()
		saved_auth = json.loads(content)
		assert saved_auth['api_token'] == 'test-api-key'
		assert saved_auth['user_id'] == 'test-user-123'


class TestAuthResilience:
	"""Test auth resilience scenarios - agent should never break due to sync failures."""

	async def test_token_expiry_handling(self, httpserver: HTTPServer, http_client, temp_config_dir):
		"""Test that expired tokens are handled gracefully."""
		# Set up successful auth flow first
		httpserver.expect_request(
			'/api/v1/oauth/device/authorize',
			method='POST',
		).respond_with_json(
			{
				'device_code': 'test-device-code',
				'user_code': 'ABCD-1234',
				'verification_uri': 'https://example.com/device',
				'verification_uri_complete': 'https://example.com/device?user_code=ABCD-1234',
				'expires_in': 1800,
				'interval': 0.1,
			}
		)

		httpserver.expect_request(
			'/api/v1/oauth/device/token',
			method='POST',
		).respond_with_json(
			{
				'access_token': 'test-api-key',
				'token_type': 'Bearer',
				'user_id': 'test-user-123',
				'scope': 'read write',
			}
		)

		# Authenticate successfully first
		auth = DeviceAuthClient(base_url=httpserver.url_for(''), http_client=http_client)
		success = await auth.authenticate(agent_session_id='test-session-id', show_instructions=False)
		assert success is True

		# Now simulate token expiry by returning 401 errors
		httpserver.expect_request(
			'/api/v1/events',
			method='POST',
		).respond_with_json({'error': 'unauthorized', 'detail': 'Token expired'}, status=401)

		# Create cloud sync service
		from browser_use.sync.service import CloudSync

		service = CloudSync(base_url=httpserver.url_for(''), enable_auth=True)
		service.auth_client = auth

		# Send event - should not raise exception even though token is expired
		await service.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Test task after token expiry',
				user_id='test-user-123',
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
				device_id='test-device-id',
			)
		)

		# Agent should continue functioning despite sync failure
		assert True  # No exception raised

	async def test_auth_failure_resilience(self, httpserver: HTTPServer, http_client, temp_config_dir):
		"""Test that auth failures don't break the agent."""
		# Set up auth endpoint to always fail
		httpserver.expect_request(
			'/api/v1/oauth/device/authorize',
			method='POST',
		).respond_with_json({'error': 'invalid_client', 'error_description': 'Client not found'}, status=400)

		auth = DeviceAuthClient(base_url=httpserver.url_for(''), http_client=http_client)

		# Auth should fail gracefully without throwing
		success = await auth.authenticate(agent_session_id='test-session-id', show_instructions=False)
		assert success is False

		# Should still be able to create sync service
		from browser_use.sync.service import CloudSync

		service = CloudSync(base_url=httpserver.url_for(''), enable_auth=True)
		service.auth_client = auth

		# Set up events endpoint to handle unauthenticated requests
		httpserver.expect_request(
			'/api/v1/events',
			method='POST',
		).respond_with_json({'processed': 1, 'failed': 0})

		# Should be able to send events without auth (pre-auth mode)
		await service.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Test task without auth',
				user_id='',
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
				device_id='test-device-id',
			)
		)

	async def test_server_downtime_resilience(self, httpserver: HTTPServer, http_client, temp_config_dir):
		"""Test that server downtime doesn't break the agent."""
		auth = DeviceAuthClient(base_url=httpserver.url_for(''), http_client=http_client)

		# Don't set up any server responses - simulate server being down

		# Auth should timeout gracefully
		result = await auth.poll_for_token('fake-device-code', interval=0.1, timeout=0.3)
		assert result is None

		from browser_use.sync.service import CloudSync

		service = CloudSync(base_url=httpserver.url_for(''), enable_auth=True)
		service.auth_client = auth

		# Should be able to send events even when server is down
		# They will be queued locally
		await service.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Test task during server downtime',
				user_id='test-user-123',
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
				device_id='test-device-id',
			)
		)

	async def test_excessive_event_queue_handling(self, httpserver: HTTPServer, http_client, temp_config_dir):
		"""Test that excessive event queuing doesn't break the agent."""
		auth = DeviceAuthClient(base_url=httpserver.url_for(''), http_client=http_client)

		from browser_use.sync.service import CloudSync

		service = CloudSync(base_url=httpserver.url_for(''), enable_auth=True)
		service.auth_client = auth

		# Send many events while server is down (no responses configured)
		for i in range(100):
			await service.handle_event(
				CreateAgentTaskEvent(
					agent_session_id='test-session',
					llm_model='test-model',
					task=f'Test task {i}',
					user_id='test-user-123',
					done_output=None,
					user_feedback_type=None,
					user_comment=None,
					gif_url=None,
					device_id='test-device-id',
				)
			)

		# Agent should still be functioning
		assert True  # No memory issues or crashes

	async def test_malformed_server_responses(self, httpserver: HTTPServer, http_client, temp_config_dir):
		"""Test that malformed server responses don't break the agent."""
		# Set up malformed JSON responses
		httpserver.expect_request(
			'/api/v1/oauth/device/authorize',
			method='POST',
		).respond_with_data('invalid json{', status=200, content_type='application/json')

		auth = DeviceAuthClient(base_url=httpserver.url_for(''), http_client=http_client)

		# Should handle malformed response gracefully
		try:
			await auth.start_device_authorization('test-session-id')
		except Exception:
			pass  # Exception is expected but shouldn't crash the agent

		# Set up another malformed response for events
		httpserver.expect_request(
			'/api/v1/events',
			method='POST',
		).respond_with_data('malformed response', status=500)

		from browser_use.sync.service import CloudSync

		service = CloudSync(base_url=httpserver.url_for(''), enable_auth=True)
		service.auth_client = auth

		# Should handle malformed event response gracefully
		await service.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Test task with malformed response',
				user_id='test-user-123',
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
				device_id='test-device-id',
			)
		)
