"""Tests for CloudSync client machinery - retry logic, event handling, backend communication."""

import os
import tempfile
from pathlib import Path

import httpx
import pytest
from bubus import BaseEvent
from pytest_httpserver import HTTPServer

from browser_use.agent.cloud_events import CreateAgentTaskEvent
from browser_use.sync.auth import TEMP_USER_ID, DeviceAuthClient
from browser_use.sync.service import CloudSync


@pytest.fixture
def temp_config_dir():
	"""Create temporary config directory for tests."""
	with tempfile.TemporaryDirectory() as tmpdir:
		temp_dir = Path(tmpdir) / '.config' / 'browseruse'
		temp_dir.mkdir(parents=True, exist_ok=True)

		os.environ['BROWSER_USE_CONFIG_DIR'] = str(temp_dir)

		yield temp_dir


@pytest.fixture
async def http_client(httpserver: HTTPServer):
	"""Create a real HTTP client pointed at the test server."""
	async with httpx.AsyncClient(base_url=httpserver.url_for('')) as client:
		yield client


class TestCloudSyncInit:
	"""Test CloudSync initialization and configuration."""

	async def test_init_with_auth_enabled(self, temp_config_dir):
		"""Test CloudSync initialization with auth enabled."""
		service = CloudSync(enable_auth=True, base_url='http://localhost:8000')

		assert service.base_url == 'http://localhost:8000'
		assert service.enable_auth is True
		assert service.auth_client is not None
		assert isinstance(service.auth_client, DeviceAuthClient)
		assert service.pending_events == []
		assert service.session_id is None

	async def test_init_with_auth_disabled(self, temp_config_dir):
		"""Test CloudSync initialization with auth disabled."""
		service = CloudSync(enable_auth=False, base_url='http://localhost:8000')

		assert service.base_url == 'http://localhost:8000'
		assert service.enable_auth is False
		assert service.auth_client is None
		assert service.pending_events == []


class TestCloudSyncEventHandling:
	"""Test CloudSync event validation and processing."""

	@pytest.fixture
	def authenticated_sync(self, httpserver: HTTPServer, http_client, temp_config_dir):
		"""Create authenticated CloudSync service."""
		auth = DeviceAuthClient(base_url=httpserver.url_for(''), http_client=http_client)
		auth.auth_config.api_token = 'test-api-key'
		auth.auth_config.user_id = 'test-user-123'

		service = CloudSync(base_url=httpserver.url_for(''), enable_auth=True)
		service.auth_client = auth
		service.session_id = 'test-session-id'
		return service

	@pytest.fixture
	def unauthenticated_sync(self, httpserver: HTTPServer, temp_config_dir):
		"""Create unauthenticated CloudSync service."""
		service = CloudSync(base_url=httpserver.url_for(''), enable_auth=True)
		service.session_id = 'test-session-id'
		return service

	async def test_event_forwarding_authenticated(self, httpserver: HTTPServer, authenticated_sync):
		"""Test event forwarding when authenticated."""
		# Capture requests
		requests = []

		def capture_request(request):
			requests.append(request.get_json())
			from werkzeug.wrappers import Response

			return Response('{"processed": 1, "failed": 0}', status=200, mimetype='application/json')

		httpserver.expect_request('/api/v1/events', method='POST').respond_with_handler(capture_request)

		# Send event
		await authenticated_sync.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Test task',
				user_id='test-user-123',
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
			)
		)

		# Verify forwarding
		assert len(requests) == 1
		event_batch = requests[0]
		assert len(event_batch['events']) == 1

		event = event_batch['events'][0]
		assert event['event_type'] == 'CreateAgentTaskEvent'
		assert event['user_id'] == 'test-user-123'
		# BaseEvent creates event_type attribute, plus our custom data as attributes
		assert event['task'] == 'Test task'

	async def test_event_queueing_unauthenticated(self, httpserver: HTTPServer, unauthenticated_sync):
		"""Test event queueing when unauthenticated."""
		# Server returns 401
		httpserver.expect_request('/api/v1/events', method='POST').respond_with_json({'error': 'unauthorized'}, status=401)

		# Send event
		await unauthenticated_sync.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Queued task',
				user_id=TEMP_USER_ID,
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
			)
		)

		# Event should be queued
		assert len(unauthenticated_sync.pending_events) == 1
		queued_event = unauthenticated_sync.pending_events[0]
		assert queued_event.event_type == 'CreateAgentTaskEvent'
		assert queued_event.user_id == TEMP_USER_ID
		assert queued_event.task == 'Queued task'

	async def test_event_user_id_injection_pre_auth(self, httpserver: HTTPServer, unauthenticated_sync):
		"""Test that temp user ID is injected for pre-auth events."""
		requests = []

		def capture_request(request):
			requests.append(request.get_json())
			from werkzeug.wrappers import Response

			return Response('{"processed": 1, "failed": 0}', status=200, mimetype='application/json')

		httpserver.expect_request('/api/v1/events', method='POST').respond_with_handler(capture_request)

		# Send event without user_id
		await unauthenticated_sync.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Pre-auth task',
				user_id=TEMP_USER_ID,
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
			)
		)

		# Verify temp user ID was injected
		assert len(requests) == 1
		event = requests[0]['events'][0]
		assert event['user_id'] == TEMP_USER_ID


class TestCloudSyncRetryLogic:
	"""Test CloudSync retry and error handling logic."""

	@pytest.fixture
	def sync_with_auth(self, httpserver: HTTPServer, http_client, temp_config_dir):
		"""Create CloudSync with auth."""
		auth = DeviceAuthClient(base_url=httpserver.url_for(''), http_client=http_client)
		auth.auth_config.api_token = 'test-api-key'
		auth.auth_config.user_id = 'test-user-123'

		service = CloudSync(base_url=httpserver.url_for(''), enable_auth=True)
		service.auth_client = auth
		service.session_id = 'test-session-id'
		return service

	async def test_pending_event_resending(self, httpserver: HTTPServer, sync_with_auth):
		"""Test resending of pending events after authentication."""
		requests = []

		def capture_request(request):
			requests.append(request.get_json())
			from werkzeug.wrappers import Response

			return Response('{"processed": 1, "failed": 0}', status=200, mimetype='application/json')

		httpserver.expect_request('/api/v1/events', method='POST').respond_with_handler(capture_request)

		# Manually add pending events (simulating 401 scenario)
		sync_with_auth.pending_events.extend(
			[
				CreateAgentTaskEvent(
					agent_session_id='test-session',
					llm_model='test-model',
					task='Pending task 1',
					user_id=TEMP_USER_ID,
					done_output=None,
					user_feedback_type=None,
					user_comment=None,
					gif_url=None,
				),
				CreateAgentTaskEvent(
					agent_session_id='test-session',
					llm_model='test-model',
					task='Pending task 2',
					user_id=TEMP_USER_ID,
					done_output=None,
					user_feedback_type=None,
					user_comment=None,
					gif_url=None,
				),
			]
		)

		# Resend pending events
		await sync_with_auth._resend_pending_events()

		# Should send all pending events with updated user ID
		assert len(requests) == 2
		for i, request in enumerate(requests):
			event = request['events'][0]
			assert event['user_id'] == 'test-user-123'  # Updated from temp ID
			assert f'Pending task {i + 1}' == event['task']

		# Pending events should be cleared
		assert len(sync_with_auth.pending_events) == 0

	async def test_backend_error_resilience(self, httpserver: HTTPServer, sync_with_auth):
		"""Test resilience to backend errors."""
		# Server returns 500 error
		httpserver.expect_request('/api/v1/events', method='POST').respond_with_data('Internal Server Error', status=500)

		# Should not raise exception
		await sync_with_auth.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Task during outage',
				user_id='test-user-123',
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
			)
		)

		# Events should not be queued for 500 errors (only 401)
		assert len(sync_with_auth.pending_events) == 0

	async def test_network_error_resilience(self, sync_with_auth):
		"""Test resilience to network errors."""
		# No server running - will get connection error
		sync_with_auth.base_url = 'http://localhost:99999'  # Invalid port

		# Should not raise exception
		await sync_with_auth.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Task during network error',
				user_id='test-user-123',
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
			)
		)

		# Should handle gracefully without crashing

	async def test_concurrent_event_sending(self, httpserver: HTTPServer, sync_with_auth):
		"""Test handling of concurrent event sending."""
		import asyncio

		requests = []

		def capture_request(request):
			requests.append(request.get_json())
			from werkzeug.wrappers import Response

			return Response('{"processed": 1, "failed": 0}', status=200, mimetype='application/json')

		httpserver.expect_request('/api/v1/events', method='POST').respond_with_handler(capture_request)

		# Send multiple events concurrently
		tasks = []
		for i in range(5):
			task = sync_with_auth.handle_event(
				CreateAgentTaskEvent(
					agent_session_id='test-session',
					llm_model='test-model',
					task=f'Concurrent task {i}',
					user_id='test-user-123',
					done_output=None,
					user_feedback_type=None,
					user_comment=None,
					gif_url=None,
				)
			)
			tasks.append(task)

		await asyncio.gather(*tasks)

		# All events should be sent
		assert len(requests) == 5
		# Just verify all events have task data - order may vary due to concurrency
		task_values = [req['events'][0]['task'] for req in requests]
		expected_tasks = [f'Concurrent task {i}' for i in range(5)]
		assert sorted(task_values) == sorted(expected_tasks)


class TestCloudSyncBackendCommunication:
	"""Test CloudSync backend communication patterns."""

	async def test_request_format_validation(self, httpserver: HTTPServer, temp_config_dir):
		"""Test that requests are formatted correctly for backend."""
		requests = []

		def capture_request(request):
			# Validate request structure
			assert request.content_type == 'application/json'
			data = request.get_json()
			requests.append(data)

			# Validate batch structure
			assert 'events' in data
			assert isinstance(data['events'], list)
			assert len(data['events']) == 1

			event = data['events'][0]
			required_fields = ['event_type', 'event_id', 'event_created_at', 'event_schema', 'user_id']
			for field in required_fields:
				assert field in event, f'Missing required field: {field}'

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

		await service.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Format validation test',
				user_id='test-user-123',
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
			)
		)

		assert len(requests) == 1

	async def test_auth_header_handling(self, httpserver: HTTPServer, temp_config_dir):
		"""Test proper auth header handling."""
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

		# Test authenticated request
		auth = DeviceAuthClient(base_url=httpserver.url_for(''))
		auth.auth_config.api_token = 'test-api-key'
		auth.auth_config.user_id = 'test-user-123'

		service = CloudSync(base_url=httpserver.url_for(''), enable_auth=True)
		service.auth_client = auth

		await service.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Auth header test',
				user_id='test-user-123',
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
			)
		)

		# Check auth header was included
		assert len(requests) == 1
		headers = requests[0]['headers']
		assert 'Authorization' in headers
		assert headers['Authorization'] == 'Bearer test-api-key'

		# Test unauthenticated request
		requests.clear()
		service.auth_client = DeviceAuthClient(base_url=httpserver.url_for(''))  # No credentials

		await service.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='No auth test',
				user_id='',
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
			)
		)

		# Check no auth header
		assert len(requests) == 1
		headers = requests[0]['headers']
		assert 'Authorization' not in headers


class TestCloudSyncErrorHandling:
	"""Test CloudSync error handling doesn't crash the agent."""

	@pytest.fixture
	def sync_service(self, httpserver: HTTPServer, temp_config_dir):
		"""Create CloudSync service."""
		return CloudSync(base_url=httpserver.url_for(''), enable_auth=False)

	async def test_timeout_error_handling(self, sync_service):
		"""Test that timeout errors are handled gracefully."""
		# Use a URL that will timeout
		sync_service.base_url = 'http://10.255.255.1'  # Non-routable IP for timeout

		# Should not raise exception
		await sync_service.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Timeout test',
				user_id='test-user-123',
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
			)
		)

	async def test_malformed_event_handling(self, httpserver: HTTPServer, sync_service):
		"""Test handling of events that can't be serialized."""

		class BadEvent(BaseEvent):
			"""Event that will fail to serialize."""

			event_type: str = 'BadEvent'

			def model_dump(self, **kwargs):
				raise ValueError('Serialization failed')

		# Should not raise exception
		await sync_service.handle_event(BadEvent())

	async def test_http_error_responses(self, httpserver: HTTPServer, sync_service):
		"""Test various HTTP error responses don't crash the service."""
		error_codes = [400, 403, 404, 429, 500, 502, 503]

		for status_code in error_codes:
			httpserver.expect_request('/api/v1/events', method='POST').respond_with_json(
				{'error': f'Test error {status_code}'}, status=status_code
			)

			# Should not raise exception
			await sync_service.handle_event(
				CreateAgentTaskEvent(
					agent_session_id='test-session',
					llm_model='test-model',
					task=f'Error {status_code} test',
					user_id='test-user-123',
					done_output=None,
					user_feedback_type=None,
					user_comment=None,
					gif_url=None,
				)
			)

	async def test_invalid_response_handling(self, httpserver: HTTPServer, sync_service):
		"""Test handling of invalid server responses."""
		# Return invalid JSON
		httpserver.expect_request('/api/v1/events', method='POST').respond_with_data('Not JSON', status=200)

		# Should not raise exception
		await sync_service.handle_event(
			CreateAgentTaskEvent(
				agent_session_id='test-session',
				llm_model='test-model',
				task='Invalid response test',
				user_id='test-user-123',
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
			)
		)

	async def test_event_with_restricted_attributes(self, httpserver: HTTPServer, sync_service):
		"""Test handling events that don't allow user_id attribute."""
		from pydantic import ConfigDict

		class RestrictedEvent(BaseEvent):
			"""Event that doesn't allow extra attributes."""

			model_config = ConfigDict(extra='forbid')
			event_type: str = 'RestrictedEvent'
			data: str = 'test'

		httpserver.expect_request('/api/v1/events', method='POST').respond_with_json({'processed': 1}, status=200)

		# Should not raise exception - will log debug message about not being able to set user_id
		await sync_service.handle_event(RestrictedEvent())

	async def test_concurrent_error_resilience(self, httpserver: HTTPServer, sync_service):
		"""Test that concurrent errors don't affect other events."""
		import asyncio

		successful_requests = []
		request_count = 0

		def handler(request):
			nonlocal request_count
			request_count += 1
			# Every 3rd request fails
			if request_count % 3 == 0:
				from werkzeug.wrappers import Response

				return Response('Server Error', status=500)
			else:
				successful_requests.append(request.get_json())
				from werkzeug.wrappers import Response

				return Response('{"processed": 1}', status=200, mimetype='application/json')

		httpserver.expect_request('/api/v1/events', method='POST').respond_with_handler(handler)

		# Send 10 events concurrently
		tasks = []
		for i in range(10):
			task = sync_service.handle_event(
				CreateAgentTaskEvent(
					agent_session_id='test-session',
					llm_model='test-model',
					task=f'Concurrent error test {i}',
					user_id='test-user-123',
					done_output=None,
					user_feedback_type=None,
					user_comment=None,
					gif_url=None,
				)
			)
			tasks.append(task)

		# All should complete without raising
		await asyncio.gather(*tasks)

		# ~7 should succeed (10 total, ~3 fail)
		assert len(successful_requests) >= 6
