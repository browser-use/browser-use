"""
Streamlined tests for cloud events emitted during agent lifecycle.

Tests the most critical event flows without excessive duplication.
"""

import base64
import json
import os
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import UUID

import pytest
from dotenv import load_dotenv

# Load environment variables before any imports
load_dotenv()
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from pytest_httpserver import HTTPServer

from browser_use.agent.cloud_events import (
	MAX_TASK_LENGTH,
	CreateAgentOutputFileEvent,
	CreateAgentSessionEvent,
	CreateAgentStepEvent,
	CreateAgentTaskEvent,
	UpdateAgentTaskEvent,
)

# Skip LLM API key verification for tests
os.environ['SKIP_LLM_API_KEY_VERIFICATION'] = 'true'

from bubus import BaseEvent

from browser_use import Agent
from browser_use.browser import BrowserSession
from browser_use.sync.service import CloudSync
from tests.ci.mocks import create_mock_llm


@pytest.fixture
async def browser_session():
	"""Create a real browser session for testing"""
	session = BrowserSession(
		headless=True,
		user_data_dir=None,  # Use temporary directory
	)
	yield session
	await session.stop()


@pytest.fixture
def mock_llm():
	"""Create a mock LLM that immediately returns done action"""
	llm = MagicMock(spec=BaseChatModel)

	# Create the JSON response that the agent would parse
	json_response = {
		'thinking': 'null',
		'evaluation_previous_goal': 'Starting task',
		'memory': 'New task to complete',
		'next_goal': 'Complete the test task',
		'action': [{'done': {'success': True, 'text': 'Test completed successfully'}}],
	}

	# Create a mock response with the JSON
	mock_response = AIMessage(content=json.dumps(json_response))

	# Make the LLM return our mock response
	llm.invoke = lambda *args, **kwargs: mock_response
	llm.ainvoke = AsyncMock(return_value=mock_response)

	# Mock the with_structured_output method to return parsed objects
	structured_llm = MagicMock()

	async def mock_structured_ainvoke(*args, **kwargs):
		# The agent will create its own AgentOutput and ActionModel classes
		# We return the raw response and let the agent parse it
		return {
			'raw': mock_response,
			'parsed': None,  # Let the agent parse it from the raw JSON
		}

	structured_llm.ainvoke = AsyncMock(side_effect=mock_structured_ainvoke)
	llm.with_structured_output = lambda *args, **kwargs: structured_llm

	# Set attributes that agent checks
	llm.model_name = 'gpt-4o'
	llm._verified_api_keys = True
	llm._verified_tool_calling_method = 'function_calling'

	return llm


@pytest.fixture
def event_collector():
	"""Collect all events emitted during tests"""
	events = []
	event_order = []

	class EventCollector:
		def __init__(self):
			self.events = events
			self.event_order = event_order

		async def collect_event(self, event: BaseEvent):
			self.events.append(event)
			self.event_order.append(event.event_type)
			return 'collected'

		def get_events_by_type(self, event_type: str) -> list[BaseEvent]:
			return [e for e in self.events if e.event_type == event_type]

		def clear(self):
			self.events.clear()
			self.event_order.clear()

	return EventCollector()


@pytest.fixture
def mock_cloud_sync():
	"""Create mocked cloud sync service."""
	sync = Mock(spec=CloudSync)
	sync.send_event = AsyncMock()
	sync.authenticate = AsyncMock(return_value=True)
	sync._authenticated = True
	sync.handle_event = AsyncMock()
	return sync


@pytest.fixture
def agent_with_cloud(browser_session, mock_cloud_sync):
	"""Create agent with cloud sync enabled."""
	with patch('browser_use.sync.CloudSync', return_value=mock_cloud_sync):
		with patch.dict(os.environ, {'BROWSERUSE_CLOUD_SYNC': 'true'}):
			agent = Agent(
				task='Test task',
				llm=create_mock_llm(),
				browser_session=browser_session,
			)
			return agent


class TestAgentEventLifecycle:
	"""Test critical agent event flows with minimal duplication"""

	async def test_agent_lifecycle_events(self, mock_llm, browser_session, event_collector, httpserver: HTTPServer):
		"""Test that all events are emitted in the correct order during agent lifecycle"""

		# Setup a test page
		httpserver.expect_request('/').respond_with_data('<html><body><h1>Test Page</h1></body></html>', content_type='text/html')

		# Navigate to test page
		await browser_session.navigate(httpserver.url_for('/'))

		# Patch environment variables to use localhost for CloudSync
		with patch.dict(
			os.environ, {'BROWSER_USE_CLOUD_URL': 'http://localhost:8000', 'BROWSER_USE_CLOUD_UI_URL': 'http://localhost:3000'}
		):
			# Create agent
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

	async def test_agent_with_gif_generation(self, mock_llm, browser_session, event_collector, httpserver: HTTPServer):
		"""Test that GIF generation triggers CreateAgentOutputFileEvent"""

		# Setup a test page
		httpserver.expect_request('/').respond_with_data('<html><body><h1>GIF Test</h1></body></html>', content_type='text/html')
		await browser_session.navigate(httpserver.url_for('/'))

		# Patch environment variables to use localhost for CloudSync
		with patch.dict(
			os.environ, {'BROWSER_USE_CLOUD_URL': 'http://localhost:8000', 'BROWSER_USE_CLOUD_UI_URL': 'http://localhost:3000'}
		):
			# Create agent with GIF generation
			agent = Agent(
				task='Test task with GIF',
				llm=mock_llm,
				browser_session=browser_session,
				generate_gif=True,  # Enable GIF generation
			)

			# Subscribe to all events
			agent.eventbus.on('*', event_collector.collect_event)

			# Run the agent
			history = await agent.run(max_steps=5)

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

	async def test_step_screenshot_capture(self, mock_llm, browser_session, event_collector, httpserver: HTTPServer):
		"""Test that screenshots are captured for each step"""

		# Setup test page
		httpserver.expect_request('/').respond_with_data(
			'<html><body><h1>Screenshot Test</h1></body></html>', content_type='text/html'
		)
		await browser_session.navigate(httpserver.url_for('/'))

		# Patch environment variables to use localhost for CloudSync
		with patch.dict(
			os.environ, {'BROWSER_USE_CLOUD_URL': 'http://localhost:8000', 'BROWSER_USE_CLOUD_UI_URL': 'http://localhost:3000'}
		):
			# Create agent
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

	async def test_agent_emits_events_to_cloud(self, agent_with_cloud, mock_cloud_sync):
		"""Test that agent emits all required events to cloud sync."""
		# Run agent
		await agent_with_cloud.run()

		# Check that events were sent to cloud sync
		calls = mock_cloud_sync.handle_event.call_args_list
		assert len(calls) >= 4  # At minimum: session, task, step, update

		# Verify we have the core event types
		event_types = [call.args[0].event_type for call in calls]
		assert 'CreateAgentSessionEvent' in event_types
		assert 'CreateAgentTaskEvent' in event_types
		assert 'CreateAgentStepEvent' in event_types
		assert 'UpdateAgentTaskEvent' in event_types

		# Verify event content
		session_events = [call for call in calls if call.args[0].event_type == 'CreateAgentSessionEvent']
		task_events = [call for call in calls if call.args[0].event_type == 'CreateAgentTaskEvent']
		step_events = [call for call in calls if call.args[0].event_type == 'CreateAgentStepEvent']

		assert len(session_events) == 1
		assert len(task_events) == 1
		assert len(step_events) >= 1

		# Verify event relationships
		session_event = session_events[0].args[0]
		task_event = task_events[0].args[0]
		step_event = step_events[0].args[0]

		assert task_event.agent_session_id == session_event.id
		assert step_event.agent_task_id == task_event.id

	async def test_agent_emits_session_start_event(self, agent_with_cloud, mock_cloud_sync):
		"""Test that agent emits session start event."""
		# Run agent
		await agent_with_cloud.run()

		# Check that session start event was sent
		calls = mock_cloud_sync.handle_event.call_args_list
		session_events = [call for call in calls if call.args[0].event_type == 'CreateAgentSessionEvent']

		assert len(session_events) == 1
		event = session_events[0].args[0]
		assert hasattr(event, 'id')
		assert hasattr(event, 'browser_session_id')

	async def test_agent_emits_task_events(self, agent_with_cloud, mock_cloud_sync):
		"""Test that agent emits task events."""
		# Run agent
		await agent_with_cloud.run()

		# Check task events
		calls = mock_cloud_sync.handle_event.call_args_list

		# Should have CreateAgentTaskEvent
		create_task_events = [call for call in calls if call.args[0].event_type == 'CreateAgentTaskEvent']
		assert len(create_task_events) == 1
		create_event = create_task_events[0].args[0]
		assert create_event.task == 'Test task'
		assert hasattr(create_event, 'agent_session_id')

		# Should have UpdateAgentTaskEvent when done
		update_task_events = [call for call in calls if call.args[0].event_type == 'UpdateAgentTaskEvent']
		assert len(update_task_events) >= 1

	async def test_cloud_sync_disabled(self, browser_session):
		"""Test that cloud sync can be disabled."""
		with patch.dict(os.environ, {'BROWSERUSE_CLOUD_SYNC': 'false'}):
			agent = Agent(
				task='Test task',
				llm=create_mock_llm(),
				browser_session=browser_session,
			)

			assert not hasattr(agent, 'cloud_sync') or agent.cloud_sync is None

			# Run agent - should work without cloud sync
			await agent.run()

	async def test_agent_error_resilience(self, agent_with_cloud, mock_cloud_sync):
		"""Test that agent continues working even if cloud sync fails."""
		# Make cloud sync fail
		mock_cloud_sync.handle_event.side_effect = Exception('Cloud sync error')

		# Run agent - should not raise exception
		result = await agent_with_cloud.run()

		# Agent should complete successfully despite sync failures
		assert result is not None
		assert result.is_done()

		# Verify cloud sync was attempted
		assert mock_cloud_sync.handle_event.call_count > 0

	async def test_session_id_persistence(self, browser_session):
		"""Test that agent session ID persists across runs."""
		mock_sync = Mock(spec=CloudSync)
		mock_sync.send_event = AsyncMock()
		mock_sync.handle_event = AsyncMock()
		mock_sync._authenticated = True

		with patch('browser_use.sync.CloudSync', return_value=mock_sync):
			with patch.dict(os.environ, {'BROWSERUSE_CLOUD_SYNC': 'true'}):
				# Create first agent
				agent1 = Agent(
					task='First task',
					llm=create_mock_llm(),
					browser_session=browser_session,
				)
				agent1.cloud_sync = mock_sync

				# Run first agent
				await agent1.run()

				# Get session ID from first run
				session_calls = [
					call for call in mock_sync.handle_event.call_args_list if call.args[0].event_type == 'CreateAgentSessionEvent'
				]
				session_id_1 = session_calls[0].args[0].id

				# Create second agent (will have different session ID)
				agent2 = Agent(
					task='Second task',
					llm=create_mock_llm(),
					browser_session=browser_session,
				)
				agent2.cloud_sync = mock_sync

				# Clear previous calls
				mock_sync.handle_event.reset_mock()

				# Run second agent
				await agent2.run()

				# Should create new session for new agent
				session_calls_2 = [
					call for call in mock_sync.handle_event.call_args_list if call.args[0].event_type == 'CreateAgentSessionEvent'
				]
				assert len(session_calls_2) == 1  # New session created

				# Should create new task with new session ID
				task_calls = [
					call for call in mock_sync.handle_event.call_args_list if call.args[0].event_type == 'CreateAgentTaskEvent'
				]
				assert len(task_calls) == 1
				session_id_2 = session_calls_2[0].args[0].id
				assert task_calls[0].args[0].agent_session_id == session_id_2
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
			),
			CreateAgentTaskEvent(
				id='0683fb03-c5da-79c9-8000-d3a39c47c652',
				user_id='0683fb03-c5da-79c9-8000-d3a39c47c650',
				agent_session_id='0683fb03-c5da-79c9-8000-d3a39c47c651',
				task='test',
				llm_model='gpt-4o',
			),
			CreateAgentStepEvent(
				user_id='0683fb03-c5da-79c9-8000-d3a39c47c650',
				agent_task_id='0683fb03-c5da-79c9-8000-d3a39c47c652',
				step=1,
				evaluation_previous_goal='eval',
				memory='mem',
				next_goal='next',
				actions=[],
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
			)

	def test_event_type_assignment(self):
		"""Test that event_type is properly set and validated"""
		event = CreateAgentTaskEvent(
			user_id='test', agent_session_id='0683fb03-c5da-79c9-8000-d3a39c47c659', llm_model='test-model', task='test'
		)

		# Event type should be automatically set
		assert event.event_type == 'CreateAgentTaskEvent'

		# Event should have valid structure
		assert event.id is not None
		assert event.event_id is not None
		assert event.event_created_at is not None
