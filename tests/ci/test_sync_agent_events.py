"""
Streamlined tests for cloud events emitted during agent lifecycle.

Tests the most critical event flows without excessive duplication.
"""

import base64
import os
from unittest.mock import patch
from uuid import UUID

import pytest
from dotenv import load_dotenv

load_dotenv()

from bubus import BaseEvent

from browser_use import Agent
from browser_use.agent.cloud_events import (
	MAX_TASK_LENGTH,
	CreateAgentOutputFileEvent,
	CreateAgentSessionEvent,
	CreateAgentStepEvent,
	CreateAgentTaskEvent,
	UpdateAgentTaskEvent,
)
from tests.ci.conftest import create_mock_llm


class TestAgentEventLifecycle:
	"""Test critical agent event flows with minimal duplication"""

	@pytest.mark.usefixtures('mock_llm', 'browser_session', 'event_collector', 'httpserver')
	async def test_agent_lifecycle_events(self, mock_llm, browser_session, event_collector, httpserver):
		"""Test that all events are emitted in the correct order during agent lifecycle"""

		# Setup a test page
		httpserver.expect_request('/').respond_with_data('<html><body><h1>Test Page</h1></body></html>', content_type='text/html')

		# Navigate to test page
		await browser_session.navigate(httpserver.url_for('/'))

		# Create agent (environment already set up by conftest.py)
		agent = Agent(
			task='Test task',
			llm=mock_llm,
			browser_session=browser_session,
			generate_gif=False,  # Don't generate GIF for faster test
		)

		# Subscribe to all events
		agent.eventbus.on('*', event_collector.collect_event)

		# Run the agent
		history = await agent.run(max_steps=5)

		# Verify we got a successful completion
		assert history.is_done()
		assert history.is_successful()

		# Verify event order - should have core events
		assert len(event_collector.event_order) >= 4, (
			f'Expected at least 4 events, got {len(event_collector.event_order)}: {event_collector.event_order}'
		)

		# Check the exact order of events - they should be processed in FIFO order
		assert event_collector.event_order[0] == 'CreateAgentSessionEvent'
		assert event_collector.event_order[1] == 'CreateAgentTaskEvent'
		assert event_collector.event_order[2] == 'CreateAgentStepEvent'
		assert event_collector.event_order[3] == 'UpdateAgentTaskEvent'

		# Verify events have required data
		session_event = next(e for e in event_collector.events if e.event_type == 'CreateAgentSessionEvent')
		task_event = next(e for e in event_collector.events if e.event_type == 'CreateAgentTaskEvent')
		step_event = next(e for e in event_collector.events if e.event_type == 'CreateAgentStepEvent')
		update_event = next(e for e in event_collector.events if e.event_type == 'UpdateAgentTaskEvent')

		# Basic validation
		assert isinstance(session_event, CreateAgentSessionEvent)
		assert session_event.id
		assert session_event.browser_session_id == browser_session.id

		assert isinstance(task_event, CreateAgentTaskEvent)
		assert task_event.id
		assert task_event.agent_session_id == session_event.id
		assert task_event.task == 'Test task'

		assert isinstance(step_event, CreateAgentStepEvent)
		assert step_event.agent_task_id == task_event.id
		assert step_event.step == 2  # Step is incremented before event is emitted
		assert step_event.url == httpserver.url_for('/')

		assert isinstance(update_event, UpdateAgentTaskEvent)
		assert update_event.id == task_event.id
		assert update_event.done_output is not None

	@pytest.mark.usefixtures('mock_llm', 'browser_session', 'event_collector', 'httpserver')
	async def test_agent_with_gif_generation(self, mock_llm, browser_session, cloud_sync, event_collector, httpserver):
		"""Test that GIF generation triggers CreateAgentOutputFileEvent"""

		# Setup cloud sync endpoint
		httpserver.expect_request('/api/v1/events', method='POST').respond_with_json(
			{'processed': 1, 'failed': 0, 'results': [{'success': True}]}
		)

		# Setup a test page
		httpserver.expect_request('/').respond_with_data('<html><body><h1>GIF Test</h1></body></html>', content_type='text/html')
		await browser_session.navigate(httpserver.url_for('/'))

		# Create agent with GIF generation
		agent = Agent(
			task='Test task with GIF',
			llm=mock_llm,
			browser_session=browser_session,
			generate_gif=True,  # Enable GIF generation
			cloud_sync=cloud_sync,
		)

		# Subscribe to all events
		agent.eventbus.on('*', event_collector.collect_event)

		# Run the agent
		_history = await agent.run(max_steps=5)

		# Verify CreateAgentOutputFileEvent was emitted
		output_file_events = event_collector.get_events_by_type('CreateAgentOutputFileEvent')
		assert len(output_file_events) == 1

		output_event = output_file_events[0]
		assert isinstance(output_event, CreateAgentOutputFileEvent)
		assert output_event.file_name.endswith('.gif')
		assert output_event.content_type == 'image/gif'
		assert output_event.task_id
		assert output_event.file_content is not None
		assert len(output_event.file_content) > 0

		# Decode and verify the base64 content is a valid GIF
		gif_bytes = base64.b64decode(output_event.file_content)
		assert gif_bytes.startswith(b'GIF87a') or gif_bytes.startswith(b'GIF89a')
		assert len(gif_bytes) > 100  # Should be a real GIF file

	@pytest.mark.usefixtures('mock_llm', 'browser_session', 'event_collector', 'httpserver')
	async def test_step_screenshot_capture(self, mock_llm, browser_session, event_collector, httpserver):
		"""Test that screenshots are captured for each step"""

		# Setup test page
		httpserver.expect_request('/').respond_with_data(
			'<html><body><h1>Screenshot Test</h1></body></html>', content_type='text/html'
		)
		await browser_session.navigate(httpserver.url_for('/'))

		# Create agent without cloud sync (not needed for screenshot test)
		agent = Agent(
			task='Test screenshot capture',
			llm=mock_llm,
			browser_session=browser_session,
			generate_gif=False,
		)

		# Subscribe to all events
		agent.eventbus.on('*', event_collector.collect_event)

		# Run the agent
		await agent.run(max_steps=3)

		# Get all step events
		step_events = event_collector.get_events_by_type('CreateAgentStepEvent')
		assert len(step_events) >= 1

		# Verify each step has a valid screenshot
		for step_event in step_events:
			assert isinstance(step_event, CreateAgentStepEvent)
			assert step_event.screenshot_url is not None
			assert step_event.screenshot_url.startswith('data:image/png;base64,')

			# Decode and validate the screenshot
			base64_data = step_event.screenshot_url.split(',')[1]
			screenshot_bytes = base64.b64decode(base64_data)

			# Verify PNG signature
			assert screenshot_bytes.startswith(b'\x89PNG\r\n\x1a\n')
			assert len(screenshot_bytes) > 1000  # Should be a real screenshot


class TestAgentCloudIntegration:
	"""Test that agent properly integrates with cloud sync service"""

	@pytest.mark.usefixtures('agent_with_cloud', 'event_collector', 'httpserver')
	async def test_agent_emits_events_to_cloud(self, agent_with_cloud, event_collector, httpserver):
		"""Test that agent emits all required events to cloud sync."""
		# Set up httpserver to capture events
		captured_events = []

		def capture_events(request):
			data = request.get_json()
			captured_events.extend(data.get('events', []))
			from werkzeug.wrappers import Response

			return Response(
				'{"processed": 1, "failed": 0, "results": [{"success": true}]}', status=200, mimetype='application/json'
			)

		httpserver.expect_request('/api/v1/events', method='POST').respond_with_handler(capture_events)

		# Subscribe to eventbus to verify events
		agent_with_cloud.eventbus.on('*', event_collector.collect_event)

		# Run agent
		await agent_with_cloud.run()

		# Verify we have the core event types in eventbus
		assert len(event_collector.event_order) >= 4  # At minimum: session, task, step, update
		assert 'CreateAgentSessionEvent' in event_collector.event_order
		assert 'CreateAgentTaskEvent' in event_collector.event_order
		assert 'CreateAgentStepEvent' in event_collector.event_order
		assert 'UpdateAgentTaskEvent' in event_collector.event_order

		# Verify events were sent to cloud
		assert len(captured_events) >= 4

		# Verify event relationships using event_collector
		session_events = event_collector.get_events_by_type('CreateAgentSessionEvent')
		task_events = event_collector.get_events_by_type('CreateAgentTaskEvent')
		step_events = event_collector.get_events_by_type('CreateAgentStepEvent')

		assert len(session_events) == 1
		assert len(task_events) == 1
		assert len(step_events) >= 1

		# Verify event relationships
		session_event = session_events[0]
		task_event = task_events[0]
		step_event = step_events[0]

		assert task_event.agent_session_id == session_event.id
		assert step_event.agent_task_id == task_event.id

	@pytest.mark.usefixtures('agent_with_cloud', 'event_collector', 'httpserver')
	async def test_agent_emits_session_start_event(self, agent_with_cloud, event_collector, httpserver):
		"""Test that agent emits session start event."""
		# Set up httpserver endpoint
		httpserver.expect_request('/api/v1/events', method='POST').respond_with_json(
			{'processed': 1, 'failed': 0, 'results': [{'success': True}]}
		)

		# Subscribe to events
		agent_with_cloud.eventbus.on('*', event_collector.collect_event)

		# Run agent
		await agent_with_cloud.run()

		# Check that session start event was sent
		session_events = event_collector.get_events_by_type('CreateAgentSessionEvent')

		assert len(session_events) == 1
		event = session_events[0]
		assert hasattr(event, 'id')
		assert hasattr(event, 'browser_session_id')

	@pytest.mark.usefixtures('agent_with_cloud', 'event_collector', 'httpserver')
	async def test_agent_emits_task_events(self, agent_with_cloud, event_collector, httpserver):
		"""Test that agent emits task events."""
		# Set up httpserver endpoint
		httpserver.expect_request('/api/v1/events', method='POST').respond_with_json(
			{'processed': 1, 'failed': 0, 'results': [{'success': True}]}
		)

		# Subscribe to events
		agent_with_cloud.eventbus.on('*', event_collector.collect_event)

		# Run agent
		await agent_with_cloud.run()

		# Check task events
		create_task_events = event_collector.get_events_by_type('CreateAgentTaskEvent')
		assert len(create_task_events) == 1
		create_event = create_task_events[0]
		assert create_event.task == 'Test task'
		assert hasattr(create_event, 'agent_session_id')

		# Should have UpdateAgentTaskEvent when done
		update_task_events = event_collector.get_events_by_type('UpdateAgentTaskEvent')
		assert len(update_task_events) >= 1

	@pytest.mark.usefixtures('browser_session')
	async def test_cloud_sync_disabled(self, browser_session):
		"""Test that cloud sync can be disabled."""
		with patch.dict(os.environ, {'BROWSER_USE_CLOUD_SYNC': 'false'}):
			agent = Agent(
				task='Test task',
				llm=create_mock_llm(),
				browser_session=browser_session,
			)

			assert not hasattr(agent, 'cloud_sync') or agent.cloud_sync is None

			# Run agent - should work without cloud sync
			await agent.run()

	@pytest.mark.usefixtures('agent_with_cloud', 'httpserver')
	async def test_agent_error_resilience(self, agent_with_cloud, httpserver):
		"""Test that agent continues working even if cloud sync fails."""

		# Make cloud endpoint fail
		def fail_handler(request):
			from werkzeug.wrappers import Response

			return Response('Server error', status=500, mimetype='text/plain')

		httpserver.expect_request('/api/v1/events', method='POST').respond_with_handler(fail_handler)

		# Run agent - should not raise exception despite cloud sync failures
		result = await agent_with_cloud.run()

		# Agent should complete successfully despite sync failures
		assert result is not None
		assert result.is_done()

	@pytest.mark.usefixtures('browser_session', 'event_collector', 'httpserver')
	async def test_session_id_persistence(self, browser_session, event_collector, httpserver):
		"""Test that agent session ID persists across runs."""
		# Set up httpserver endpoint
		httpserver.expect_request('/api/v1/events', method='POST').respond_with_json(
			{'processed': 1, 'failed': 0, 'results': [{'success': True}]}
		)

		# Import CloudSync to create instances
		from browser_use.sync.service import CloudSync

		# Create first CloudSync instance
		cloud_sync1 = CloudSync(
			base_url=httpserver.url_for(''),
			enable_auth=False,
		)

		# Create first agent
		agent1 = Agent(
			task='First task',
			llm=create_mock_llm(),
			browser_session=browser_session,
			cloud_sync=cloud_sync1,
		)
		agent1.eventbus.on('*', event_collector.collect_event)

		# Run first agent
		await agent1.run()

		# Get session ID from first run
		session_events = event_collector.get_events_by_type('CreateAgentSessionEvent')
		assert len(session_events) == 1
		session_id_1 = session_events[0].id

		# Clear event collector
		event_collector.clear()

		# Create second CloudSync instance
		cloud_sync2 = CloudSync(
			base_url=httpserver.url_for(''),
			enable_auth=False,
		)

		# Create second agent (will have different session ID)
		agent2 = Agent(
			task='Second task',
			llm=create_mock_llm(),
			browser_session=browser_session,
			cloud_sync=cloud_sync2,
		)
		agent2.eventbus.on('*', event_collector.collect_event)

		# Run second agent
		await agent2.run()

		# Should create new session for new agent
		session_events_2 = event_collector.get_events_by_type('CreateAgentSessionEvent')
		assert len(session_events_2) == 1  # New session created
		session_id_2 = session_events_2[0].id

		# Should create new task with new session ID
		task_events = event_collector.get_events_by_type('CreateAgentTaskEvent')
		assert len(task_events) == 1
		assert task_events[0].agent_session_id == session_id_2
		assert session_id_2 != session_id_1  # Different session IDs


class TestEventValidation:
	"""Test event structure and validation"""

	async def test_event_base_fields(self):
		"""Test that all events have required base fields"""
		# Create a few events
		events_to_test = [
			CreateAgentSessionEvent(
				id='0683fb03-c5da-79c9-8000-d3a39c47c651',
				user_id='0683fb03-c5da-79c9-8000-d3a39c47c650',
				browser_session_id='test-browser',
				browser_session_live_url='https://example.com',
				browser_session_cdp_url='ws://localhost:9222',
				device_id='test-device-id',
			),
			CreateAgentTaskEvent(
				id='0683fb03-c5da-79c9-8000-d3a39c47c652',
				user_id='0683fb03-c5da-79c9-8000-d3a39c47c650',
				agent_session_id='0683fb03-c5da-79c9-8000-d3a39c47c651',
				task='test',
				llm_model='gpt-4o',
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
				device_id='test-device-id',
			),
			CreateAgentStepEvent(
				user_id='0683fb03-c5da-79c9-8000-d3a39c47c650',
				agent_task_id='0683fb03-c5da-79c9-8000-d3a39c47c652',
				step=1,
				evaluation_previous_goal='eval',
				memory='mem',
				next_goal='next',
				actions=[],
				screenshot_url='data:image/png;...',
				device_id='test-device-id',
			),
		]

		# Check all events have required fields
		for event in events_to_test:
			# Base event fields
			assert isinstance(event, BaseEvent)
			assert event.event_type is not None
			assert event.event_id is not None
			assert event.event_created_at is not None
			assert isinstance(event.event_path, list)

			# Check event_id is a valid UUID string
			uuid_obj = UUID(event.event_id)
			assert str(uuid_obj) == event.event_id

	def test_max_string_length_validation(self):
		"""Test that string fields enforce max length"""
		# Create event with very long task
		long_task = 'x' * (2 * MAX_TASK_LENGTH)  # Longer than MAX_TASK_LENGTH

		# Should raise validation error for string too long
		with pytest.raises(ValueError, match=f'String should have at most {MAX_TASK_LENGTH} characters'):
			CreateAgentTaskEvent(
				user_id='test',
				agent_session_id='0683fb03-c5da-79c9-8000-d3a39c47c659',
				llm_model='test-model',
				task=long_task,
				done_output=None,
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
				device_id='test-device-id',
			)

	def test_event_type_assignment(self):
		"""Test that event_type is properly set and validated"""
		event = CreateAgentTaskEvent(
			user_id='test',
			agent_session_id='0683fb03-c5da-79c9-8000-d3a39c47c659',
			llm_model='test-model',
			task='test',
			done_output=None,
			user_feedback_type=None,
			user_comment=None,
			gif_url=None,
			device_id='test-device-id',
		)

		# Event type should be automatically set
		assert event.event_type == 'CreateAgentTaskEvent'

		# Event should have valid structure
		assert event.id is not None
		assert event.event_id is not None
		assert event.event_created_at is not None
