"""
Integration tests for cloud events emitted during agent lifecycle.

Tests that all cloud events defined in cloud_events.py are properly
emitted in the correct order during agent execution.
"""

import base64
import json
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from pytest_httpserver import HTTPServer
from uuid_extensions import uuid7str

from browser_use.agent.cloud_events import (
	CreateAgentOutputFileEvent,
	CreateAgentSessionEvent,
	CreateAgentStepEvent,
	CreateAgentTaskEvent,
	UpdateAgentTaskEvent,
)

# Skip LLM API key verification for tests
os.environ['SKIP_LLM_API_KEY_VERIFICATION'] = 'true'

from browser_use import Agent
from browser_use.browser import BrowserSession
from browser_use.eventbus import (
	BaseEvent,
)


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
		'current_state': {
			'evaluation_previous_goal': 'Starting task',
			'memory': 'New task to complete',
			'next_goal': 'Complete the test task',
		},
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
	event_timestamps = []

	class EventCollector:
		def __init__(self):
			self.events = events
			self.event_order = event_order
			self.event_timestamps = event_timestamps

		async def collect_event(self, event: BaseEvent):
			import time

			collection_time = time.time()
			self.events.append(event)
			self.event_order.append(event.event_type)
			self.event_timestamps.append((event.event_type, event.event_created_at, collection_time))
			return 'collected'

		def get_events_by_type(self, event_type: str) -> list[BaseEvent]:
			return [e for e in self.events if e.event_type == event_type]

		def clear(self):
			self.events.clear()
			self.event_order.clear()
			self.event_timestamps.clear()

	return EventCollector()


class TestAgentCloudEvents:
	"""Test that cloud events are properly emitted during agent lifecycle"""

	async def test_agent_lifecycle_events(self, mock_llm, browser_session, event_collector, httpserver: HTTPServer):
		"""Test that all events are emitted in the correct order during agent lifecycle"""

		# Setup a test page
		httpserver.expect_request('/').respond_with_data('<html><body><h1>Test Page</h1></body></html>', content_type='text/html')

		# Navigate to test page
		await browser_session.navigate(httpserver.url_for('/'))

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

		# Verify event order
		assert len(event_collector.event_order) >= 4, (
			f'Expected at least 4 events, got {len(event_collector.event_order)}: {event_collector.event_order}'
		)

		# Check the exact order of events - they should be processed in FIFO order
		assert event_collector.event_order[0] == 'CreateAgentSession', (
			f'First event should be CreateAgentSession, got {event_collector.event_order[0]}'
		)
		assert event_collector.event_order[1] == 'CreateAgentTask', (
			f'Second event should be CreateAgentTask, got {event_collector.event_order[1]}'
		)
		assert event_collector.event_order[2] == 'CreateAgentStep', (
			f'Third event should be CreateAgentStep, got {event_collector.event_order[2]}'
		)
		assert event_collector.event_order[3] == 'UpdateAgentTask', (
			f'Fourth event should be UpdateAgentTask, got {event_collector.event_order[3]}'
		)

		# Verify that events were collected in the same order they were emitted (FIFO)
		collection_times = [t[2] for t in event_collector.event_timestamps]
		for i in range(1, len(collection_times)):
			assert collection_times[i] >= collection_times[i - 1], (
				f'Event {i} was collected before event {i - 1}, violating FIFO order'
			)

		# Verify emission times follow expected order (Session and Task should be emitted before Step)
		session_event = next(e for e in event_collector.events if e.event_type == 'CreateAgentSession')
		task_event = next(e for e in event_collector.events if e.event_type == 'CreateAgentTask')
		step_event = next(e for e in event_collector.events if e.event_type == 'CreateAgentStep')
		update_event = next(e for e in event_collector.events if e.event_type == 'UpdateAgentTask')

		# Session should be created before Task (foreign key constraint)
		assert session_event.event_created_at <= task_event.event_created_at, (
			'Session event should be emitted before or at same time as Task event'
		)
		# Task should be created before Step (foreign key constraint)
		assert task_event.event_created_at <= step_event.event_created_at, (
			'Task event should be emitted before or at same time as Step event'
		)
		# All create events should happen before update
		assert step_event.event_created_at <= update_event.event_created_at, (
			'Step event should be emitted before or at same time as UpdateTask event'
		)

		# Verify CreateAgentSessionEvent
		assert isinstance(session_event, CreateAgentSessionEvent)
		assert session_event.id  # Should have session ID
		assert session_event.browser_session_id == browser_session.id
		assert session_event.user_id == ''  # Empty for agent, filled by cloud handler

		# Verify CreateAgentTaskEvent
		assert isinstance(task_event, CreateAgentTaskEvent)
		assert task_event.id  # Should have task ID
		assert task_event.agent_session_id == session_event.id
		assert task_event.task == 'Test task'
		assert task_event.event_started_at is not None
		assert task_event.stopped is False
		assert task_event.paused is False
		assert task_event.done_output is None  # Not done yet at creation

		# Verify CreateAgentStepEvent
		assert isinstance(step_event, CreateAgentStepEvent)
		assert step_event.agent_task_id == task_event.id
		assert step_event.step == 2  # Step is incremented before event is emitted
		assert step_event.actions  # Should have actions
		assert step_event.url == httpserver.url_for('/')

		# Verify screenshot is captured and base64 encoded
		assert step_event.screenshot_url is not None, 'Screenshot should be captured for each step'
		assert step_event.screenshot_url.startswith('data:image/png;base64,'), (
			f'Screenshot should be base64 PNG data URL, got: {step_event.screenshot_url[:50]}...'
		)

		# Decode and verify the screenshot is a valid PNG
		try:
			base64_data = step_event.screenshot_url.split(',')[1]
			screenshot_bytes = base64.b64decode(base64_data)

			# Verify PNG signature (starts with PNG magic bytes)
			assert screenshot_bytes.startswith(b'\x89PNG\r\n\x1a\n'), (
				f'Invalid PNG signature. First 8 bytes: {screenshot_bytes[:8]}'
			)

			# Verify screenshot has reasonable size
			assert len(screenshot_bytes) > 1000, f'Screenshot too small: {len(screenshot_bytes)} bytes'

			print(f'Screenshot captured: {len(screenshot_bytes)} bytes')

		except Exception as e:
			pytest.fail(f'Failed to decode screenshot: {e}')

		# Verify UpdateAgentTaskEvent
		assert isinstance(update_event, UpdateAgentTaskEvent)
		assert update_event.id == task_event.id  # Should update the same task
		assert update_event.done_output is not None  # Should have final output
		assert update_event.finished_at is not None  # Should have completion time
		assert update_event.stopped is False
		assert update_event.paused is False
		assert update_event.agent_state is not None

	async def test_agent_with_gif_generation_events(
		self, mock_llm, browser_session, event_collector, httpserver: HTTPServer, tmp_path
	):
		"""Test that GIF generation triggers CreateAgentOutputFileEvent with real base64 content"""

		# Setup a test page
		httpserver.expect_request('/').respond_with_data(
			'<html><body><h1>Test Page for GIF</h1></body></html>', content_type='text/html'
		)

		# Navigate to test page
		await browser_session.navigate(httpserver.url_for('/'))

		# Create agent with GIF generation (using True to auto-generate path)
		agent = Agent(
			task='Test task with GIF',
			llm=mock_llm,
			browser_session=browser_session,
			generate_gif=True,  # Use True to auto-generate path
		)

		# Subscribe to all events
		agent.eventbus.on('*', event_collector.collect_event)

		# Run the agent
		history = await agent.run(max_steps=5)

		# Verify CreateAgentOutputFileEvent was emitted
		output_file_events = [e for e in event_collector.events if e.event_type == 'CreateAgentOutputFile']
		assert len(output_file_events) == 1

		output_event = output_file_events[0]
		assert isinstance(output_event, CreateAgentOutputFileEvent)
		assert output_event.file_name.endswith('.gif'), f'Expected .gif file, got {output_event.file_name}'
		assert output_event.content_type == 'image/gif'
		assert output_event.task_id  # Should reference the task
		assert output_event.file_content is not None, 'GIF file content should not be None'
		assert len(output_event.file_content) > 0, 'GIF file content should not be empty'

		# Decode and verify the base64 content is a valid GIF
		try:
			gif_bytes = base64.b64decode(output_event.file_content)
		except Exception as e:
			pytest.fail(f'Failed to decode base64 content: {e}')

		# Verify GIF file signature (starts with 'GIF87a' or 'GIF89a')
		assert gif_bytes.startswith(b'GIF87a') or gif_bytes.startswith(b'GIF89a'), (
			f'Invalid GIF signature. First 6 bytes: {gif_bytes[:6]}'
		)

		# Verify GIF has reasonable size (should be more than minimal header)
		assert len(gif_bytes) > 100, f'GIF too small: {len(gif_bytes)} bytes'

		# Verify the file was actually created if a path was specified
		# Note: Agent might create temp files, so we just verify the event has the content
		print(f'GIF generated: {output_event.file_name}, size: {len(gif_bytes)} bytes')

		# Verify event order - GIF event should come after UpdateAgentTask
		update_index = event_collector.event_order.index('UpdateAgentTask')
		gif_index = event_collector.event_order.index('CreateAgentOutputFile')
		assert gif_index > update_index, 'GIF event should come after UpdateAgentTask'

	async def test_agent_step_screenshots_captured(self, mock_llm, browser_session, event_collector, httpserver: HTTPServer):
		"""Test that screenshots are captured and properly base64 encoded for each step"""

		# Setup test pages for multi-step interaction
		httpserver.expect_request('/page1').respond_with_data(
			'<html><body><h1>Page 1</h1><button onclick="window.location=\'/page2\'">Go to Page 2</button></body></html>',
			content_type='text/html',
		)
		httpserver.expect_request('/page2').respond_with_data(
			'<html><body><h1>Page 2</h1><p>Task completed!</p></body></html>', content_type='text/html'
		)

		# Navigate to first page
		await browser_session.navigate(httpserver.url_for('/page1'))

		# Create a mock LLM that performs navigation then completes
		llm = MagicMock(spec=BaseChatModel)
		step_count = 0
		base_url = httpserver.url_for('')

		def get_response_for_step(*args, **kwargs):
			nonlocal step_count
			step_count += 1

			if step_count == 1:
				# First step: navigate to page 2
				json_response = {
					'current_state': {
						'evaluation_previous_goal': 'Starting on page 1',
						'memory': 'Need to navigate to page 2',
						'next_goal': 'Navigate to page 2',
					},
					'action': [{'go_to_url': {'url': f'{base_url}page2'}}],
				}
			else:
				# Second step: done
				json_response = {
					'current_state': {
						'evaluation_previous_goal': 'Successfully navigated to page 2',
						'memory': 'Reached final page',
						'next_goal': 'Task complete',
					},
					'action': [{'done': {'success': True, 'text': 'Successfully navigated to page 2'}}],
				}

			return AIMessage(content=json.dumps(json_response))

		llm.invoke = get_response_for_step
		llm.ainvoke = AsyncMock(side_effect=get_response_for_step)

		# Mock structured output
		structured_llm = MagicMock()

		async def mock_structured(*args, **kwargs):
			response = get_response_for_step()
			return {'raw': response, 'parsed': None}

		structured_llm.ainvoke = AsyncMock(side_effect=mock_structured)
		llm.with_structured_output = lambda *args, **kwargs: structured_llm

		llm.model_name = 'gpt-4o'
		llm._verified_api_keys = True
		llm._verified_tool_calling_method = 'function_calling'

		# Create agent
		agent = Agent(
			task='Navigate from page 1 to page 2',
			llm=llm,
			browser_session=browser_session,
			generate_gif=False,
		)

		# Subscribe to all events
		agent.eventbus.on('*', event_collector.collect_event)

		# Run the agent
		history = await agent.run(max_steps=3)

		# Verify completion
		assert history.is_done()
		assert history.is_successful()

		# Get all step events
		step_events = [e for e in event_collector.events if e.event_type == 'CreateAgentStep']
		assert len(step_events) >= 2, f'Expected at least 2 step events, got {len(step_events)}'

		# Verify each step has a valid screenshot
		for i, step_event in enumerate(step_events):
			assert isinstance(step_event, CreateAgentStepEvent)

			# Check screenshot exists and is properly formatted
			assert step_event.screenshot_url is not None, f'Step {i + 1} missing screenshot'
			assert step_event.screenshot_url.startswith('data:image/png;base64,'), (
				f'Step {i + 1} screenshot should be base64 PNG data URL'
			)

			# Decode and validate the screenshot
			try:
				base64_data = step_event.screenshot_url.split(',')[1]
				screenshot_bytes = base64.b64decode(base64_data)

				# Verify PNG signature
				assert screenshot_bytes.startswith(b'\x89PNG\r\n\x1a\n'), f'Step {i + 1} has invalid PNG signature'

				# Verify reasonable screenshot size
				assert len(screenshot_bytes) > 1000, f'Step {i + 1} screenshot too small: {len(screenshot_bytes)} bytes'

				print(f'Step {i + 1} screenshot: {len(screenshot_bytes)} bytes')

			except Exception as e:
				pytest.fail(f'Failed to decode step {i + 1} screenshot: {e}')

		print(f'Successfully validated screenshots for {len(step_events)} steps')


class TestCloudEventValidation:
	"""Test cloud event validation and structure"""

	async def test_agent_session_event_structure(self):
		"""Test CreateAgentSessionEvent structure and validation"""
		event = CreateAgentSessionEvent(
			id='test-session-id',
			user_id='test-user',
			browser_session_id='test-browser-session-id',
			browser_session_live_url='https://example.com',
			browser_session_cdp_url='ws://localhost:9222',
			browser_state={
				'viewport': {'width': 1920, 'height': 1080},
				'user_agent': 'Mozilla/5.0 Test User Agent',
				'headless': True,
			},
		)

		# Test validation
		assert event.event_type == 'CreateAgentSession'
		assert event.id == 'test-session-id'
		assert event.user_id == 'test-user'
		assert event.browser_session_id == 'test-browser-session-id'
		assert event.browser_state['viewport']['width'] == 1920
		assert not event.browser_session_stopped

	async def test_agent_task_event_structure(self):
		"""Test CreateAgentTaskEvent structure and validation"""
		session_id = uuid7str()
		task_id = uuid7str()

		event = CreateAgentTaskEvent(
			id=task_id,
			user_id='test-user',
			agent_session_id=session_id,
			task='Test task',
			llm_model='gpt-4o',
			done_output='Task completed successfully',
			started_at=datetime.utcnow(),
			finished_at=datetime.utcnow(),
			agent_state={'n_steps': 1},
		)

		# Test validation
		assert event.event_type == 'CreateAgentTask'
		assert event.id == task_id
		assert event.user_id == 'test-user'
		assert event.agent_session_id == session_id
		assert event.task == 'Test task'
		assert event.llm_model == 'gpt-4o'
		assert not event.stopped
		assert not event.paused
		assert isinstance(event.agent_state, dict)

	async def test_agent_step_event_structure(self):
		"""Test CreateAgentStepEvent structure and validation"""
		task_id = uuid7str()

		event = CreateAgentStepEvent(
			id=uuid7str(),
			user_id='test-user',
			agent_task_id=task_id,
			step=1,
			evaluation_previous_goal='Starting the task',
			memory='Memory from previous steps',
			next_goal='Complete the current goal',
			actions=[{'name': 'click', 'args': {'selector': 'button#submit'}}],
			url='https://example.com',
			screenshot_url='data:image/png;base64,iVBORw0KGgo=',
		)

		# Test validation
		assert event.event_type == 'CreateAgentStep'
		assert event.step == 1
		assert event.user_id == 'test-user'
		assert event.agent_task_id == task_id
		assert len(event.actions) == 1
		assert event.actions[0]['name'] == 'click'
		assert event.url == 'https://example.com'
		assert event.screenshot_url.startswith('data:image/png;base64,')

	async def test_update_agent_task_event_structure(self):
		"""Test UpdateAgentTaskEvent structure and validation"""
		task_id = uuid7str()

		event = UpdateAgentTaskEvent(
			id=task_id,  # The task ID to update
			user_id='test-user',
			# Only update some fields
			stopped=True,
			done_output='Task completed with results',
			finished_at=datetime.utcnow(),
			agent_state={'final_state': True, 'n_steps': 10},
		)

		# Test validation
		assert event.event_type == 'UpdateAgentTask'
		assert event.id == task_id
		assert event.user_id == 'test-user'
		assert event.stopped is True
		assert event.paused is None  # Not updated
		assert event.done_output == 'Task completed with results'
		assert event.agent_state == {'final_state': True, 'n_steps': 10}

	def test_max_string_length_validation(self):
		"""Test that string fields enforce max length"""
		# Create event with very long task
		long_task = 'x' * 10000  # Longer than MAX_TASK_LENGTH (5000)

		# Should raise validation error for string too long
		with pytest.raises(ValueError, match='String should have at most 5000 characters'):
			CreateAgentTaskEvent(
				user_id='test',
				agent_session_id='0683fb03-c5da-79c9-8000-d3a39c47c659',
				llm_model='test-model',
				task=long_task,
			)

	def test_all_events_have_required_base_fields(self):
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
			CreateAgentOutputFileEvent(
				user_id='test',
				task_id='0683fb03-c5da-79c9-8000-d3a39c47c652',
				file_name='test.txt',
				file_content=base64.b64encode(b'test').decode(),
			),
			UpdateAgentTaskEvent(
				id='0683fb03-c5da-79c9-8000-d3a39c47c652',
				user_id='test',
				stopped=True,
				done_output='Task completed',
				finished_at=datetime.now(UTC),
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
			try:
				# Should be able to parse as UUID
				uuid_obj = UUID(event.event_id)
				assert str(uuid_obj) == event.event_id
			except ValueError:
				pytest.fail(f'Invalid UUID in event_id: {event.event_id}')

	def test_event_type_frozen_field(self):
		"""Test that event_type fields are frozen"""
		event = CreateAgentTaskEvent(
			user_id='test', agent_session_id='0683fb03-c5da-79c9-8000-d3a39c47c659', llm_model='test-model', task='test'
		)

		# Should not be able to change event_type
		with pytest.raises(ValueError):
			event.event_type = 'DifferentType'
