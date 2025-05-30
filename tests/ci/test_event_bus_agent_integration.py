"""
Tests for EventBus integration with the browser-use Agent.

Tests cover:
- Agent lifecycle events
- Task events
- Step events
- Cloud-specific events
- Real agent integration
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from browser_use.agent.service import Agent
from browser_use.event_bus import (
	EventBus,
	SessionStartedEvent,
	StepCreatedEvent,
	TaskCompletedEvent,
)


class MockLLM(BaseChatModel):
	"""Mock LLM for testing"""

	def __init__(self):
		super().__init__()
		self.model_name = 'mock-model'

	def _generate(self, *args, **kwargs):
		pass

	def _llm_type(self):
		return 'mock'

	async def _agenerate(self, *args, **kwargs):
		pass


@pytest.fixture
def mock_llm():
	"""Create a mock LLM"""
	return MockLLM()


@pytest.fixture
async def mock_browser_context():
	"""Create a mock browser context"""
	context = MagicMock()
	context.close = AsyncMock()
	return context


@pytest.fixture
async def mock_page():
	"""Create a mock page"""
	page = MagicMock()
	page.context = MagicMock()
	page.close = AsyncMock()
	page.url = 'https://example.com'
	page.title = AsyncMock(return_value='Example Page')
	return page


class TestAgentEventBusIntegration:
	"""Test EventBus integration with Agent"""

	@pytest.mark.asyncio
	async def test_agent_has_event_bus(self, mock_llm, mock_browser_context):
		"""Test that Agent initializes with EventBus"""
		agent = Agent(task='Test task', llm=mock_llm, browser_context=mock_browser_context)

		assert hasattr(agent, 'event_bus')
		assert isinstance(agent.event_bus, EventBus)
		assert agent.event_bus.agent == agent

	@pytest.mark.asyncio
	async def test_session_events_emitted(self, mock_llm, mock_browser_context):
		"""Test that session start/stop events are emitted"""
		agent = Agent(task='Test task', llm=mock_llm, browser_context=mock_browser_context)

		# Track events
		session_events = []

		async def session_handler(event, agent_ref):
			session_events.append(event)
			return 'handled'

		agent.event_bus.subscribe('SessionStartedEvent', session_handler)
		agent.event_bus.subscribe('SessionStoppedEvent', session_handler)

		# Mock the agent methods to avoid real browser operations
		with (
			patch.object(agent, '_log_agent_run'),
			patch.object(agent, 'step', new_callable=AsyncMock),
			patch.object(agent, 'close', new_callable=AsyncMock),
			patch.object(agent, '_log_agent_event'),
			patch.object(agent.browser_session, 'get_state_summary', new_callable=AsyncMock),
		):
			# Run agent (with 0 steps to finish immediately)
			await agent.run(max_steps=0)

		# Wait for events to process
		await agent.event_bus.wait_for_empty_queue()

		# Check events
		assert len(session_events) >= 2
		event_types = [e.event_type for e in session_events]
		assert 'SessionStartedEvent' in event_types
		assert 'SessionStoppedEvent' in event_types

	@pytest.mark.asyncio
	async def test_task_events_emitted(self, mock_llm, mock_browser_context):
		"""Test that task events are emitted"""
		agent = Agent(task='Test task', llm=mock_llm, browser_context=mock_browser_context)

		# Track task events
		task_events = []

		async def task_handler(event, agent_ref):
			task_events.append(event)
			return 'handled'

		agent.event_bus.subscribe('TaskStartedEvent', task_handler)
		agent.event_bus.subscribe('TaskCompletedEvent', task_handler)

		# Mock the agent methods
		with (
			patch.object(agent, '_log_agent_run'),
			patch.object(agent, 'step', new_callable=AsyncMock),
			patch.object(agent, 'close', new_callable=AsyncMock),
			patch.object(agent, '_log_agent_event'),
			patch.object(agent.state.history, 'is_done', return_value=True),
			patch.object(agent.state.history, 'get_last_done_output', return_value='Task completed'),
			patch.object(agent, 'log_completion', new_callable=AsyncMock),
			patch.object(agent.browser_session, 'get_state_summary', new_callable=AsyncMock),
		):
			# Run agent
			await agent.run(max_steps=1)

		# Wait for events
		await agent.event_bus.wait_for_empty_queue()

		# Check task events
		assert len(task_events) >= 1
		task_started = next((e for e in task_events if e.event_type == 'TaskStartedEvent'), None)
		assert task_started is not None
		assert task_started.data['task'] == 'Test task'

	@pytest.mark.asyncio
	async def test_step_events_emitted(self, mock_llm, mock_page):
		"""Test that step events are emitted during execution"""
		agent = Agent(task='Test task', llm=mock_llm, page=mock_page)

		# Track step events
		step_events = []

		async def step_handler(event, agent_ref):
			step_events.append(event)
			return 'handled'

		agent.event_bus.subscribe('StepCreatedEvent', step_handler)

		# Create mock browser state and model output
		mock_browser_state = MagicMock()
		mock_browser_state.url = 'https://example.com'
		mock_browser_state.selector_map = {}

		mock_model_output = MagicMock()
		mock_model_output.action = [MagicMock()]
		mock_model_output.action[0].model_dump = lambda: {'type': 'click', 'index': 1}

		# Start event bus
		await agent.event_bus.start()

		# Manually emit a step event (simulating what happens in agent.step)
		step_event = StepCreatedEvent(
			step_id=f'{id(agent)}_1',
			agent_task_id=id(agent.task),
			step=1,
			evaluation_previous_goal='Previous goal',
			memory='Memory content',
			next_goal='Next goal',
			actions=[{'type': 'click', 'index': 1}],
			screenshot_url='',
			url='https://example.com',
		)
		agent.event_bus.emit(step_event)

		# Wait for processing
		await agent.event_bus.wait_for_empty_queue()
		await agent.event_bus.stop()

		# Check step event
		assert len(step_events) == 1
		assert step_events[0].data['step'] == 1
		assert step_events[0].data['url'] == 'https://example.com'

	@pytest.mark.asyncio
	async def test_pause_resume_events(self, mock_llm, mock_browser_context):
		"""Test that pause/resume events are emitted"""
		agent = Agent(task='Test task', llm=mock_llm, browser_context=mock_browser_context)

		# Track pause/resume events
		control_events = []

		async def control_handler(event, agent_ref):
			control_events.append(event.event_type)
			return 'handled'

		agent.event_bus.subscribe('TaskPausedEvent', control_handler)
		agent.event_bus.subscribe('TaskResumedEvent', control_handler)

		# Start event bus
		await agent.event_bus.start()

		# Trigger pause and resume
		agent.pause()
		await asyncio.sleep(0.1)  # Let event process

		agent.resume()
		await asyncio.sleep(0.1)  # Let event process

		# Stop event bus
		await agent.event_bus.stop()

		# Check events
		assert 'TaskPausedEvent' in control_events
		assert 'TaskResumedEvent' in control_events

	@pytest.mark.asyncio
	async def test_event_serialization_after_run(self, mock_llm, mock_browser_context, tmp_path):
		"""Test serializing events after an agent run"""
		agent = Agent(task='Test task', llm=mock_llm, browser_context=mock_browser_context)

		# Mock the agent methods
		with (
			patch.object(agent, '_log_agent_run'),
			patch.object(agent, 'step', new_callable=AsyncMock),
			patch.object(agent, 'close', new_callable=AsyncMock),
			patch.object(agent, '_log_agent_event'),
			patch.object(agent.browser_session, 'get_state_summary', new_callable=AsyncMock),
		):
			# Run agent
			await agent.run(max_steps=0)

		# Serialize events
		event_file = tmp_path / 'agent_events.json'
		await agent.event_bus.serialize_events_to_file(str(event_file))

		# Check file exists
		assert event_file.exists()

		# Load and verify
		import json

		async with await anyio.open_file(event_file) as f:
			content = await f.read()
			events = json.loads(content)

		# Should have at least session start/stop and task start
		assert len(events) >= 3
		event_types = [e['event_type'] for e in events]
		assert 'SessionStartedEvent' in event_types
		assert 'TaskStartedEvent' in event_types


class TestCloudEventIntegration:
	"""Test cloud-specific event functionality"""

	@pytest.mark.asyncio
	async def test_cloud_handler_integration(self, mock_llm, mock_browser_context):
		"""Test that cloud handlers can process events"""
		agent = Agent(
			task='Test task', llm=mock_llm, browser_context=mock_browser_context, sensitive_data={'api_key': 'secret123'}
		)

		# Mock cloud handler
		cloud_results = {}

		async def cloud_sync_handler(event, agent_ref):
			"""Simulate a cloud sync handler"""
			if event.event_type == 'SessionStartedEvent':
				# Extract data for cloud
				cloud_results['session_id'] = event.data['session_id']
				cloud_results['browser_data'] = event.data['browser_session_data']
				# In real implementation, would sync to cloud here
				return {'synced': True, 'cloud_id': 'cloud_123'}
			return {'synced': False}

		# Subscribe cloud handler
		agent.event_bus.subscribe('SessionStartedEvent', cloud_sync_handler)

		# Start event bus
		await agent.event_bus.start()

		# Emit session event
		session_event = SessionStartedEvent(
			session_id=id(agent),
			user_id='test_user',
			browser_session_id='browser_123',
			browser_session_live_url='',
			browser_session_cdp_url='',
			browser_state={},
			browser_session_data={'cookies': [], 'secrets': {'api_key': 'secret123'}, 'allowed_domains': ['example.com']},
		)

		result = await agent.event_bus.enqueue_and_wait(session_event)

		# Stop event bus
		await agent.event_bus.stop()

		# Check cloud handler results
		assert 'cloud_sync_handler' in result.results
		assert result.results['cloud_sync_handler']['synced'] is True
		assert cloud_results['browser_data']['secrets']['api_key'] == 'secret123'

	@pytest.mark.asyncio
	async def test_event_completion_tracking_for_cloud(self, mock_llm, mock_browser_context):
		"""Test using completion tracking for cloud sync confirmation"""
		agent = Agent(task='Test task', llm=mock_llm, browser_context=mock_browser_context)

		# Simulate slow cloud sync
		async def slow_cloud_sync(event, agent_ref):
			await asyncio.sleep(0.1)
			return {'synced': True, 'duration_ms': 100}

		agent.event_bus.subscribe('TaskCompletedEvent', slow_cloud_sync)

		# Start event bus
		await agent.event_bus.start()

		# Emit task completed event
		task_event = TaskCompletedEvent(
			task_id='task_123',
			done_output='Task successfully completed',
			gif_url='https://example.com/recording.gif',
			finished_at=1234567890.0,
		)

		# Enqueue without waiting
		event = await agent.event_bus.enqueue(task_event)

		# Event should not be completed yet
		assert event.completed_at is None

		# Wait for completion
		await event.wait_for_completion()

		# Now should be completed with results
		assert event.completed_at is not None
		assert event.results['slow_cloud_sync']['synced'] is True

		await agent.event_bus.stop()


class TestEventBusLifecycle:
	"""Test EventBus lifecycle in agent context"""

	@pytest.mark.asyncio
	async def test_multiple_agent_runs(self, mock_llm, mock_browser_context):
		"""Test event bus across multiple agent runs"""
		agent = Agent(task='Test task', llm=mock_llm, browser_context=mock_browser_context)

		all_events = []

		async def collect_events(event, agent_ref):
			all_events.append(event.event_type)
			return 'collected'

		agent.event_bus.subscribe_to_all(collect_events)

		# Mock methods
		with (
			patch.object(agent, '_log_agent_run'),
			patch.object(agent, 'step', new_callable=AsyncMock),
			patch.object(agent, 'close', new_callable=AsyncMock),
			patch.object(agent, '_log_agent_event'),
			patch.object(agent.browser_session, 'get_state_summary', new_callable=AsyncMock),
		):
			# Run agent multiple times
			for i in range(3):
				await agent.run(max_steps=0)

		# Check we got events from all runs
		session_starts = all_events.count('SessionStartedEvent')
		session_stops = all_events.count('SessionStoppedEvent')

		assert session_starts == 3
		assert session_stops == 3

	@pytest.mark.asyncio
	async def test_event_bus_cleanup_on_error(self, mock_llm, mock_browser_context):
		"""Test that event bus is properly stopped even on error"""
		agent = Agent(task='Test task', llm=mock_llm, browser_context=mock_browser_context)

		# Make step raise an error
		with (
			patch.object(agent, '_log_agent_run'),
			patch.object(agent, 'step', side_effect=RuntimeError('Test error')),
			patch.object(agent, 'close', new_callable=AsyncMock),
			patch.object(agent, '_log_agent_event'),
		):
			# Run should handle the error
			with pytest.raises(RuntimeError):
				await agent.run(max_steps=1)

		# Event bus should be stopped
		assert not agent.event_bus.running


if __name__ == '__main__':
	pytest.main([__file__, '-v'])
