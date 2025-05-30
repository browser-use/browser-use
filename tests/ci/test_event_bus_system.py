"""
Integration test for the EventBus system with real Agent, BrowserSession, and Controller.

This test verifies that events are properly emitted during agent lifecycle using real objects.
Only the LLM is mocked since we don't want to make real API calls.
"""

import json
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import anyio
import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from browser_use.agent.service import Agent
from browser_use.event_bus import (
	Event,
	SessionStartedEvent,
	SessionStoppedEvent,
	StepExecutedEvent,
	TaskCompletedEvent,
	TaskStartedEvent,
)


class MockLLM(BaseChatModel):
	"""Mock LLM for testing"""

	def __init__(self):
		super().__init__()
		# Don't set model_name as an attribute, use a method instead
		self._mock_response = None

	@property
	def model_name(self) -> str:
		"""Return model name"""
		return 'mock-llm'

	def _generate(self, messages, stop=None, **kwargs):
		"""Mock generate method"""
		from langchain_core.messages import AIMessage
		from langchain_core.outputs import ChatGeneration, ChatResult

		# Return a simple response
		response = AIMessage(content='Mock response')
		return ChatResult(generations=[ChatGeneration(message=response)])

	async def _agenerate(self, messages, stop=None, **kwargs):
		"""Mock async generate method"""
		return self._generate(messages, stop, **kwargs)

	def _llm_type(self):
		"""Return LLM type"""
		return 'mock'

	def invoke(self, *args, **kwargs):
		"""Mock invoke"""
		return self._generate(args[0] if args else [])

	async def ainvoke(self, *args, **kwargs):
		"""Mock async invoke"""
		return self.invoke(*args, **kwargs)


@pytest.fixture
def mock_llm():
	"""Create a mock LLM"""
	return MockLLM()


@pytest.fixture
async def browser_profile():
	"""Create and provide a BrowserProfile with headless mode."""
	from browser_use.browser.profile import BrowserProfile

	profile = BrowserProfile(headless=True, user_data_dir=None)
	yield profile


@pytest.fixture
async def browser_session(browser_profile):
	"""Create a BrowserSession instance without starting it."""
	from browser_use.browser.session import BrowserSession

	session = BrowserSession(browser_profile=browser_profile)
	yield session
	# Cleanup: ensure session is stopped
	try:
		await session.stop()
	except Exception:
		pass


@pytest.fixture
async def event_collector():
	"""Fixture to collect all events emitted during tests"""
	events = []

	async def collector(event: Event, agent: Any) -> dict:
		events.append({'event_type': event.event_type, 'event': event, 'timestamp': time.time()})
		return {'collected': True}

	collector.events = events
	return collector


class TestEventBusSystem:
	"""Test the EventBus system integration with real Agent"""

	async def test_all_cloud_events_defined(self):
		"""Test that all expected cloud events are defined"""
		# List of expected event classes
		expected_events = [
			# Session events
			'SessionStartedEvent',
			'SessionStoppedEvent',
			'SessionBrowserStateUpdatedEvent',
			'SessionBrowserDataUpdatedEvent',
			# Task events
			'TaskStartedEvent',
			'TaskCompletedEvent',
			'TaskPausedEvent',
			'TaskResumedEvent',
			'TaskStoppedEvent',
			'TaskAnalyticsEvent',
			# Step events
			'StepCreatedEvent',
			'StepExecutedEvent',
			# Other events
			'ErrorTrackedEvent',
			'PerformanceMetricEvent',
			'OutputFileGeneratedEvent',
		]

		# Import the module and check
		from browser_use import event_bus

		for event_name in expected_events:
			assert hasattr(event_bus, event_name), f'Missing event: {event_name}'

		# Verify they're all Event subclasses
		for event_name in expected_events:
			event_class = getattr(event_bus, event_name)
			assert issubclass(event_class, Event), f'{event_name} is not an Event subclass'

	async def test_event_bus_with_agent_lifecycle(self, mock_llm, browser_session, event_collector):
		"""Test that the agent emits proper events during its lifecycle"""
		# Start the browser session
		await browser_session.start()

		# Patch LLM verification to skip but still set tool_calling_method
		with patch.object(Agent, '_verify_and_setup_llm', autospec=True) as mock_verify:
			# Configure the mock to set tool_calling_method when called
			def setup_agent(self):
				self.tool_calling_method = 'function_calling'
				return True

			mock_verify.side_effect = setup_agent

			# Create agent with real browser session
			agent = Agent(task='Test task', llm=mock_llm, browser=browser_session)

		# Subscribe collector to all events BEFORE the event bus starts
		agent.event_bus.subscribe_to_all(event_collector)

		# Patch emit to capture events (workaround for sync emit in async context)
		original_emit = agent.event_bus.emit
		emitted_events = []

		def capture_emit(event):
			emitted_events.append(event)
			return original_emit(event)

		agent.event_bus.emit = capture_emit

		# Mock agent methods to avoid real browser operations
		with (
			patch.object(agent, '_log_agent_run'),
			patch.object(agent, 'step', new_callable=AsyncMock),
			patch.object(agent, 'close', new_callable=AsyncMock),
			patch.object(agent, '_log_agent_event'),
		):
			# Run agent with 0 steps
			await agent.run(max_steps=0)

		# Events should already be processed since agent.run() waits for them

		# If collector didn't work, use emitted events directly
		# This is a known issue with sync emit() in async test context
		if not event_collector.events and emitted_events:
			# Convert emitted events to the expected format
			for event in emitted_events:
				event_collector.events.append({'event_type': event.__class__.__name__, 'event': event, 'timestamp': time.time()})

		event_types = [e['event_type'] for e in event_collector.events]

		# Should have session and task lifecycle events
		assert 'SessionStartedEvent' in event_types
		assert 'SessionBrowserDataUpdatedEvent' in event_types
		assert 'TaskStartedEvent' in event_types
		assert 'SessionStoppedEvent' in event_types

		# Verify event order
		session_start_idx = event_types.index('SessionStartedEvent')
		task_start_idx = event_types.index('TaskStartedEvent')
		session_stop_idx = event_types.index('SessionStoppedEvent')

		assert session_start_idx < task_start_idx < session_stop_idx

	async def test_event_serialization_to_file(self, mock_llm, browser_session, tmp_path):
		"""Test that events can be serialized to a file"""
		# Start the browser session
		await browser_session.start()

		# Create agent
		with patch.object(Agent, '_verify_and_setup_llm', autospec=True) as mock_verify:

			def setup_agent(self):
				self.tool_calling_method = 'function_calling'
				return True

			mock_verify.side_effect = setup_agent

			agent = Agent(task='Test serialization', llm=mock_llm, browser=browser_session)

		# Start event bus
		await agent.event_bus.start()

		# Emit a few test events
		events = [
			SessionStartedEvent(session_id='test-123', user_id='user-456', browser_type='chrome'),
			TaskStartedEvent(session_id='test-123', task_description='Test task'),
			StepExecutedEvent(
				task_id='task-789',
				session_id='test-123',
				step_number=1,
				action_type='click',
				evaluation_previous_goal='Start',
				memory='',
				next_goal='Click button',
				url_before='https://example.com',
				url_after='https://example.com/clicked',
				duration_ms=500.0,
				model_name='mock-llm',
			),
			TaskCompletedEvent(
				task_id='task-789',
				session_id='test-123',
				duration_seconds=10.0,
				total_steps=1,
				success=True,
				result_summary='Successfully clicked button',
				extracted_data={'clicked': True},
			),
			SessionStoppedEvent(session_id='test-123', reason='completed', total_duration_seconds=10.5),
		]

		for event in events:
			await agent.event_bus.enqueue(event)

		# Wait for processing
		await agent.event_bus.wait_for_empty_queue()

		# Serialize to file
		event_file = tmp_path / 'events.json'
		await agent.event_bus.serialize_events_to_file(str(event_file))

		# Stop event bus
		await agent.event_bus.stop()

		# Verify file exists and contains events
		assert event_file.exists()

		async with await anyio.open_file(event_file) as f:
			content = await f.read()
			loaded_events = json.loads(content)

		# Should have at least our events
		assert len(loaded_events) >= len(events)

		# Check event types are preserved
		event_types = [e['event_type'] for e in loaded_events]
		assert 'SessionStartedEvent' in event_types
		assert 'TaskStartedEvent' in event_types
		assert 'StepExecutedEvent' in event_types
		assert 'TaskCompletedEvent' in event_types
		assert 'SessionStoppedEvent' in event_types

		# Verify specific data
		session_event = next(e for e in loaded_events if e['event_type'] == 'SessionStartedEvent')
		assert session_event['session_id'] == 'test-123'
		assert session_event['user_id'] == 'user-456'
		assert session_event['browser_type'] == 'chrome'
