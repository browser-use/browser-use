"""
Comprehensive tests for the EventBus implementation.

Tests cover:
- Basic event enqueueing and processing
- Sync and async contexts
- Handler registration and execution
- FIFO ordering
- Parallel handler execution
- Error handling
- Write-ahead logging
- Serialization
- Batch operations
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Any

import pytest
from pydantic import Field

from browser_use.agent.cloud_events import CreateAgentTaskEvent
from browser_use.eventbus import BaseEvent, EventBus


# Test event models
class UserActionEvent(BaseEvent):
	"""Test event model for user actions"""

	event_type: str = Field(default='UserActionEvent', frozen=True)
	action: str
	user_id: str
	metadata: dict[str, Any] = Field(default_factory=dict)


class SystemEventModel(BaseEvent):
	"""Test event model for system events"""

	event_type: str = Field(default='SystemEventModel', frozen=True)
	event_name: str
	severity: str = 'info'
	details: dict[str, Any] = Field(default_factory=dict)


class MockAgent:
	"""Mock agent for testing"""

	def __init__(self, name: str = 'TestAgent'):
		self.name = name
		self.events_received = []


@pytest.fixture
async def eventbus():
	"""Create an event bus for testing"""
	agent = MockAgent()
	bus = EventBus()
	yield bus
	await bus.stop()


@pytest.fixture
def mock_agent():
	"""Create a mock agent"""
	return MockAgent()


class TestEventBusBasics:
	"""Test basic EventBus functionality"""

	async def test_eventbus_initialization(self, mock_agent):
		"""Test that EventBus initializes correctly"""
		bus = EventBus()

		assert bus._is_running is False
		assert bus._runloop_task is None
		assert len(bus.event_history) == 0
		assert len(bus.handlers['*']) == 1  # Default logger

	async def test_auto_start_and_stop(self, mock_agent):
		"""Test auto-start functionality and stopping the event bus"""
		bus = EventBus()

		# Should not be running initially
		assert bus._is_running is False
		assert bus._runloop_task is None

		# Auto-start by emitting an event
		bus.dispatch(UserActionEvent(action='test', user_id='user123'))
		await bus.wait_until_idle()

		# Should be running after auto-start
		assert bus._is_running is True
		assert bus._runloop_task is not None

		# Stop the bus
		await bus.stop()
		assert bus._is_running is False

		# Stop again should be idempotent
		await bus.stop()
		assert bus._is_running is False


class TestEventEnqueueing:
	"""Test event enqueueing functionality"""

	async def test_emit_and_result(self, eventbus):
		"""Test event emission in async and sync contexts, and result() pattern"""
		# Test async emission
		event = UserActionEvent(action='login', user_id='user123')
		result = eventbus.dispatch(event)

		# Check immediate result
		assert isinstance(result, UserActionEvent)
		assert result.event_type == 'UserActionEvent'
		assert result.action == 'login'
		assert result.user_id == 'user123'
		assert result.event_id is not None
		assert result.event_created_at is not None
		assert result.event_started_at is None  # Not started yet
		assert result.event_completed_at is None  # Not completed yet

		# Test result() pattern
		processed = await result.result()
		assert processed.event_started_at is not None
		assert processed.event_completed_at is not None
		assert processed.event_results['_default_log_handler'] == 'logged'

		# Check event history
		assert len(eventbus.event_history) == 1

	def test_emit_sync(self, mock_agent):
		"""Test sync event emission"""
		bus = EventBus()
		event = SystemEventModel(event_name='startup', severity='info')
		result = bus.dispatch(event)

		# Check result and write-ahead log
		assert isinstance(result, SystemEventModel)
		assert result.event_type == 'SystemEventModel'
		assert len(bus.event_history) == 1


class TestHandlerRegistration:
	"""Test handler registration and execution"""

	async def test_handler_registration(self, eventbus):
		"""Test handler registration via string, model class, and wildcard"""
		results = {'specific': [], 'model': [], 'universal': []}

		# Handler for specific event type by string
		async def user_handler(event: UserActionEvent) -> str:
			results['specific'].append(event.action)
			return 'user_handled'

		# Handler for event type by model class
		async def system_handler(event: SystemEventModel) -> str:
			results['model'].append(event.event_name)
			return 'system_handled'

		# Universal handler
		async def universal_handler(event: BaseEvent) -> str:
			results['universal'].append(event.event_type)
			return 'universal'

		# Register handlers
		eventbus.on('UserActionEvent', user_handler)
		eventbus.on(SystemEventModel, system_handler)
		eventbus.on('*', universal_handler)

		# Emit events
		eventbus.dispatch(UserActionEvent(action='login', user_id='u1'))
		eventbus.dispatch(SystemEventModel(event_name='startup'))
		await eventbus.wait_until_idle()

		# Verify all handlers were called correctly
		assert results['specific'] == ['login']
		assert results['model'] == ['startup']
		assert set(results['universal']) == {'UserActionEvent', 'SystemEventModel'}

	async def test_multiple_handlers_parallel(self, eventbus):
		"""Test that multiple handlers run in parallel"""
		start_times = []
		end_times = []

		async def slow_handler_1(event: BaseEvent) -> str:
			start_times.append(('h1', time.time()))
			await asyncio.sleep(0.1)
			end_times.append(('h1', time.time()))
			return 'handler1'

		async def slow_handler_2(event: BaseEvent) -> str:
			start_times.append(('h2', time.time()))
			await asyncio.sleep(0.1)
			end_times.append(('h2', time.time()))
			return 'handler2'

		# Subscribe both handlers
		eventbus.on('UserActionEvent', slow_handler_1)
		eventbus.on('UserActionEvent', slow_handler_2)

		# Emit event and wait
		start = time.time()
		event = await eventbus.dispatch(UserActionEvent(action='test', user_id='u1')).result()
		duration = time.time() - start

		# Check handlers ran in parallel (should take ~0.1s, not 0.2s)
		assert duration < 0.15
		assert len(start_times) == 2
		assert len(end_times) == 2

		# Check results
		assert event.event_results['slow_handler_1'] == 'handler1'
		assert event.event_results['slow_handler_2'] == 'handler2'

	def test_handler_can_be_sync_or_async(self, mock_agent):
		"""Test that both sync and async handlers are accepted"""
		bus = EventBus()

		def sync_handler(event: BaseEvent) -> str:
			return 'sync'

		async def async_handler(event: BaseEvent) -> str:
			return 'async'

		# Both should work
		bus.on('TestEvent', sync_handler)
		bus.on('TestEvent', async_handler)

		# Check both were registered
		assert len(bus.handlers['TestEvent']) == 2


class TestFIFOOrdering:
	"""Test FIFO event processing"""

	async def test_fifo_with_varying_handler_delays(self, eventbus):
		"""Test FIFO order is maintained with varying handler processing times"""
		processed_order = []
		handler_start_times = []

		async def handler(event: UserActionEvent) -> int:
			order = event.metadata.get('order', -1)
			handler_start_times.append((order, asyncio.get_event_loop().time()))
			# Variable delays to test ordering
			if order % 2 == 0:
				await asyncio.sleep(0.05)  # Even events take longer
			else:
				await asyncio.sleep(0.01)  # Odd events are quick
			processed_order.append(order)
			return order

		eventbus.on('UserActionEvent', handler)

		# Emit 20 events rapidly
		for i in range(20):
			eventbus.dispatch(UserActionEvent(action=f'test_{i}', user_id='u1', metadata={'order': i}))

		await eventbus.wait_until_idle()

		# Verify FIFO order maintained
		assert processed_order == list(range(20))
		# Verify handler start times are in order
		for i in range(1, len(handler_start_times)):
			assert handler_start_times[i][1] >= handler_start_times[i - 1][1]


class TestErrorHandling:
	"""Test error handling in handlers"""

	async def test_error_handling(self, eventbus):
		"""Test handler error capture and isolation"""
		results = []

		async def failing_handler(event: BaseEvent) -> str:
			raise ValueError('Expected to fail')

		async def working_handler(event: BaseEvent) -> str:
			results.append('success')
			return 'worked'

		# Register both handlers
		eventbus.on('UserActionEvent', failing_handler)
		eventbus.on('UserActionEvent', working_handler)

		# Emit and wait for result
		event = await eventbus.dispatch(UserActionEvent(action='test', user_id='u1')).result()

		# Verify error capture and isolation
		assert 'failing_handler' in event.event_errors
		assert 'Expected to fail' in event.event_errors['failing_handler']
		assert event.event_results['working_handler'] == 'worked'
		assert results == ['success']


class TestBatchOperations:
	"""Test batch event operations"""

	async def test_batch_emit_with_gather(self, eventbus):
		"""Test batch event emission with asyncio.gather"""
		events = [
			UserActionEvent(action='login', user_id='u1'),
			SystemEventModel(event_name='startup'),
			UserActionEvent(action='logout', user_id='u1'),
		]

		# Enqueue batch
		emitted_events = [eventbus.dispatch(event) for event in events]
		results = await asyncio.gather(*[event.result() for event in emitted_events])

		# Check all processed
		assert len(results) == 3
		for result in results:
			assert result.event_completed_at is not None
			assert '_default_log_handler' in result.event_results


class TestWriteAheadLog:
	"""Test write-ahead logging functionality"""

	async def test_write_ahead_log_captures_all_events(self, eventbus):
		"""Test that all events are captured in write-ahead log"""
		# Emit several events
		events = []
		for i in range(5):
			event = UserActionEvent(action=f'action_{i}', user_id='u1')
			events.append(eventbus.dispatch(event))

		await eventbus.wait_until_idle()

		# Check write-ahead log
		log = eventbus.event_history.copy()
		assert len(log) == 5
		for i, event in enumerate(log.values()):
			assert event.action == f'action_{i}'

		# Check event state properties
		completed = eventbus.events_completed
		pending = eventbus.events_queued
		processing = eventbus.events_started
		assert len(completed) + len(pending) + len(processing) == len(log)
		assert len(completed) == 5  # All events should be completed
		assert len(pending) == 0  # No events should be pending
		assert len(processing) == 0  # No events should be processing


class TestEventCompletion:
	"""Test event completion tracking"""

	async def test_wait_for_result(self, eventbus):
		"""Test waiting for event completion"""
		completion_order = []

		async def slow_handler(event: BaseEvent) -> str:
			await asyncio.sleep(0.1)
			completion_order.append('handler_done')
			return 'done'

		eventbus.on('UserActionEvent', slow_handler)

		# Enqueue without waiting
		event = eventbus.dispatch(UserActionEvent(action='test', user_id='u1'))
		completion_order.append('enqueue_done')

		# Wait for completion
		await event.result()
		completion_order.append('wait_done')

		# Check order
		assert completion_order == ['enqueue_done', 'handler_done', 'wait_done']
		assert event.event_completed_at is not None


class TestEdgeCases:
	"""Test edge cases and special scenarios"""

	async def test_stop_with_pending_events(self, mock_agent):
		"""Test stopping event bus with events still in queue"""
		bus = EventBus()

		# Add a slow handler
		async def slow_handler(event: BaseEvent) -> str:
			await asyncio.sleep(1)
			return 'done'

		bus.on('*', slow_handler)

		# Enqueue events but don't wait
		for i in range(5):
			bus.dispatch(UserActionEvent(action=f'action_{i}', user_id='u1'))

		# Stop immediately
		await bus.stop()

		# Bus should stop even with pending events
		assert not bus._is_running

	async def test_event_with_complex_data(self, eventbus):
		"""Test events with complex nested data"""
		complex_data = {
			'nested': {
				'list': [1, 2, {'inner': 'value'}],
				'datetime': datetime.utcnow(),
				'none': None,
			}
		}

		event = SystemEventModel(event_name='complex', details=complex_data)

		result = await eventbus.dispatch(event).result()

		# Check data preserved
		assert result.details['nested']['list'][2]['inner'] == 'value'

	async def test_concurrent_emit_calls(self, eventbus):
		"""Test multiple concurrent emit calls"""
		# Create many events concurrently
		tasks = []
		for i in range(100):
			event = UserActionEvent(action=f'concurrent_{i}', user_id='u1')
			# Emit returns the event synchronously, but we need to wait for completion
			emitted_event = eventbus.dispatch(event)
			tasks.append(emitted_event.result())

		# Wait for all events to complete
		await asyncio.gather(*tasks)

		# Wait for processing
		await eventbus.wait_until_idle()

		# Check all events in log
		log = eventbus.event_history.copy()
		assert len(log) == 100

	async def test_mixed_delay_handlers_maintain_order(self, eventbus):
		"""Test that events with different handler delays still maintain FIFO order"""
		collected_orders = []
		handler_start_times = []

		async def handler(event: UserActionEvent):
			order = event.metadata.get('order', -1)
			handler_start_times.append((order, asyncio.get_event_loop().time()))
			# Simulate varying processing times
			if order % 2 == 0:
				await asyncio.sleep(0.05)  # Even events take longer
			else:
				await asyncio.sleep(0.01)  # Odd events are quick
			collected_orders.append(order)
			return f'handled_{order}'

		eventbus.on('UserActionEvent', handler)

		# Emit events
		num_events = 20
		for i in range(num_events):
			event = UserActionEvent(action=f'mixed_{i}', user_id='u1', metadata={'order': i})
			eventbus.dispatch(event)

		# Wait for all events to process
		await eventbus.wait_until_idle()

		# Verify exact FIFO order despite different processing times
		assert collected_orders == list(range(num_events)), f'Events processed out of order: {collected_orders}'

		# Verify handler start times are in order (events are dequeued in FIFO order)
		for i in range(1, len(handler_start_times)):
			prev_order, prev_time = handler_start_times[i - 1]
			curr_order, curr_time = handler_start_times[i]
			assert curr_time >= prev_time, f'Event {curr_order} started before event {prev_order}'


class TestEventTypeOverride:
	"""Test that Event subclasses properly override event_type"""

	async def test_event_subclass_type(self, eventbus):
		"""Test that event subclasses maintain their type"""
		from browser_use.agent.cloud_events import CreateAgentTaskEvent

		# Create a specific event type
		event = CreateAgentTaskEvent(
			user_id='test_user', agent_session_id='12345678-1234-5678-1234-567812345678', llm_model='test-model', task='test task'
		)

		# Enqueue it
		result = eventbus.dispatch(event)

		# Check type is preserved - should be class name
		assert result.event_type == 'CreateAgentTask'
		assert isinstance(result, BaseEvent)

	async def test_event_schema_auto_generation(self, eventbus):
		"""Test that event_schema is automatically set with the correct format"""
		from browser_use.utils import get_browser_use_version

		version = get_browser_use_version()

		# Test various event types
		base_event = BaseEvent(event_type='TestEvent')
		assert base_event.event_schema == f'browser_use.eventbus.models.BaseEvent@{version}'

		task_event = CreateAgentTaskEvent(
			user_id='test_user', agent_session_id='12345678-1234-5678-1234-567812345678', llm_model='test-model', task='test task'
		)
		assert task_event.event_schema == f'browser_use.agent.cloud_events.CreateAgentTaskEvent@{version}'

		user_event = UserActionEvent(action='login', user_id='user123')
		assert user_event.event_schema == f'test_eventbus.UserActionEvent@{version}'

		# Check schema is preserved after emit
		result = eventbus.dispatch(task_event)
		assert result.event_schema == task_event.event_schema


class TestWALPersistence:
	"""Test automatic WAL persistence functionality"""

	async def test_wal_persistence_handler(self, tmp_path):
		"""Test that events are automatically persisted to WAL file"""
		# Create event bus with WAL path
		wal_path = tmp_path / 'test_events.jsonl'
		bus = EventBus(name='TestBus', wal_path=wal_path)

		try:
			# Emit some events
			events = []
			for i in range(3):
				event = UserActionEvent(action=f'action_{i}', user_id=f'user_{i}')
				emitted_event = bus.dispatch(event)
				result = await emitted_event.result()
				events.append(result)

			# Wait for processing
			await bus.wait_until_idle()

			# Check WAL file exists
			assert wal_path.exists()

			# Read and verify JSONL content
			lines = wal_path.read_text().strip().split('\n')
			assert len(lines) == 3

			# Parse each line as JSON
			for i, line in enumerate(lines):
				data = json.loads(line)
				assert data['action'] == f'action_{i}'
				assert data['user_id'] == f'user_{i}'
				assert data['event_type'] == 'UserActionEvent'
				assert isinstance(data['event_created_at'], str)
				assert isinstance(data['event_completed_at'], str)
				datetime.fromisoformat(data['event_created_at'])
				datetime.fromisoformat(data['event_completed_at'])

		finally:
			await bus.stop()

	async def test_wal_persistence_creates_parent_dir(self, tmp_path):
		"""Test that WAL persistence creates parent directories"""
		# Use a nested path that doesn't exist
		wal_path = tmp_path / 'nested' / 'dirs' / 'events.jsonl'
		assert not wal_path.parent.exists()

		# Create event bus
		bus = EventBus(name='TestBus', wal_path=wal_path)

		# Parent directory should be created
		assert wal_path.parent.exists()
		try:
			# Emit an event
			await bus.dispatch(UserActionEvent(action='test', user_id='u1')).result()

			# Wait for WAL persistence to complete
			await bus.wait_until_idle()

			# Check file was created
			assert wal_path.exists()
		finally:
			await bus.stop()

	async def test_wal_persistence_skips_incomplete_events(self, tmp_path):
		"""Test that WAL persistence only writes completed events"""
		wal_path = tmp_path / 'incomplete_events.jsonl'
		bus = EventBus(name='TestBus', wal_path=wal_path)

		try:
			# Add a slow handler that will delay completion
			async def slow_handler(event: BaseEvent) -> str:
				await asyncio.sleep(0.1)
				return 'slow'

			bus.on('UserActionEvent', slow_handler)

			# Emit event without waiting
			event = bus.dispatch(UserActionEvent(action='test', user_id='u1'))

			# Check file doesn't exist yet (event not completed)
			assert not wal_path.exists()

			# Wait for completion
			await event.result()
			await bus.wait_until_idle()

			# Now file should exist with completed event
			assert wal_path.exists()
			lines = wal_path.read_text().strip().split('\n')
			assert len(lines) == 1
			data = json.loads(lines[0])
			assert data['event_type'] == 'UserActionEvent'
			assert 'event_completed_at' in data

		finally:
			await bus.stop()


class TestEventBusHierarchy:
	"""Test hierarchical EventBus subscription patterns"""

	async def test_three_level_hierarchy_bubbling(self):
		"""Test that events bubble up through a 3-level hierarchy and event_path is correct"""
		# Create three EventBus instances in a hierarchy
		parent_bus = EventBus(name='ParentBus')
		child_bus = EventBus(name='ChildBus')
		subchild_bus = EventBus(name='SubchildBus')

		# Track events received at each level
		events_at_parent = []
		events_at_child = []
		events_at_subchild = []

		async def parent_handler(event: BaseEvent) -> str:
			events_at_parent.append(event)
			return 'parent_received'

		async def child_handler(event: BaseEvent) -> str:
			events_at_child.append(event)
			return 'child_received'

		async def subchild_handler(event: BaseEvent) -> str:
			events_at_subchild.append(event)
			return 'subchild_received'

		# Register handlers
		parent_bus.on('*', parent_handler)
		child_bus.on('*', child_handler)
		subchild_bus.on('*', subchild_handler)

		# Subscribe buses to each other: parent <- child <- subchild
		# Child forwards events to parent
		child_bus.on('*', parent_bus.dispatch)
		# Subchild forwards events to child
		subchild_bus.on('*', child_bus.dispatch)

		try:
			# Emit event from the bottom of hierarchy
			event = UserActionEvent(action='bubble_test', user_id='test_user')
			emitted = subchild_bus.dispatch(event)

			# Wait for event to bubble up
			await subchild_bus.wait_until_idle()
			await child_bus.wait_until_idle()
			await parent_bus.wait_until_idle()

			# Verify event was received at all levels
			assert len(events_at_subchild) == 1
			assert len(events_at_child) == 1
			assert len(events_at_parent) == 1

			# Verify event_path shows the complete journey
			final_event = events_at_parent[0]
			assert final_event.event_path == ['SubchildBus', 'ChildBus', 'ParentBus']

			# Verify it's the same event content
			assert final_event.action == 'bubble_test'
			assert final_event.user_id == 'test_user'
			assert final_event.event_id == emitted.event_id

			# Test event emitted at middle level
			events_at_parent.clear()
			events_at_child.clear()
			events_at_subchild.clear()

			middle_event = SystemEventModel(event_name='middle_test')
			child_bus.dispatch(middle_event)

			await child_bus.wait_until_idle()
			await parent_bus.wait_until_idle()

			# Should only reach child and parent, not subchild
			assert len(events_at_subchild) == 0
			assert len(events_at_child) == 1
			assert len(events_at_parent) == 1
			assert events_at_parent[0].event_path == ['ChildBus', 'ParentBus']

		finally:
			await parent_bus.stop()
			await child_bus.stop()
			await subchild_bus.stop()

	async def test_circular_subscription_prevention(self):
		"""Test that circular EventBus subscriptions don't create infinite loops"""
		# Create three peer EventBus instances
		peer1 = EventBus(name='Peer1')
		peer2 = EventBus(name='Peer2')
		peer3 = EventBus(name='Peer3')

		# Track events at each peer
		events_at_peer1 = []
		events_at_peer2 = []
		events_at_peer3 = []

		async def peer1_handler(event: BaseEvent) -> str:
			events_at_peer1.append(event)
			return 'peer1_received'

		async def peer2_handler(event: BaseEvent) -> str:
			events_at_peer2.append(event)
			return 'peer2_received'

		async def peer3_handler(event: BaseEvent) -> str:
			events_at_peer3.append(event)
			return 'peer3_received'

		# Register handlers
		peer1.on('*', peer1_handler)
		peer2.on('*', peer2_handler)
		peer3.on('*', peer3_handler)

		# Create circular subscription: peer1 -> peer2 -> peer3 -> peer1
		peer1.on('*', peer2.dispatch)
		peer2.on('*', peer3.dispatch)
		peer3.on('*', peer1.dispatch)  # This completes the circle

		try:
			# Emit event from peer1
			event = UserActionEvent(action='circular_test', user_id='test_user')
			emitted = peer1.dispatch(event)

			# Wait for all processing to complete
			await asyncio.sleep(0.2)  # Give time for any potential loops
			await peer1.wait_until_idle()
			await peer2.wait_until_idle()
			await peer3.wait_until_idle()

			# Each peer should receive the event exactly once
			assert len(events_at_peer1) == 1
			assert len(events_at_peer2) == 1
			assert len(events_at_peer3) == 1

			# Check event paths show the propagation but no loops
			assert events_at_peer1[0].event_path == ['Peer1', 'Peer2', 'Peer3']
			assert events_at_peer2[0].event_path == ['Peer1', 'Peer2', 'Peer3']
			assert events_at_peer3[0].event_path == ['Peer1', 'Peer2', 'Peer3']

			# The event should NOT come back to peer1 from peer3
			# because peer3's emit handler will detect peer1 is already in the path

			# Verify all events have the same ID (same event, not duplicates)
			assert all(e.event_id == emitted.event_id for e in [events_at_peer1[0], events_at_peer2[0], events_at_peer3[0]])

			# Test starting from a different peer
			events_at_peer1.clear()
			events_at_peer2.clear()
			events_at_peer3.clear()

			event2 = SystemEventModel(event_name='circular_test_2')
			peer2.dispatch(event2)

			await asyncio.sleep(0.2)
			await peer1.wait_until_idle()
			await peer2.wait_until_idle()
			await peer3.wait_until_idle()

			# Should visit peer2 -> peer3 -> peer1, then stop
			assert len(events_at_peer1) == 1
			assert len(events_at_peer2) == 1
			assert len(events_at_peer3) == 1

			assert events_at_peer2[0].event_path == ['Peer2', 'Peer3', 'Peer1']
			assert events_at_peer3[0].event_path == ['Peer2', 'Peer3', 'Peer1']
			assert events_at_peer1[0].event_path == ['Peer2', 'Peer3', 'Peer1']

		finally:
			await peer1.stop()
			await peer2.stop()
			await peer3.stop()


if __name__ == '__main__':
	pytest.main([__file__, '-v'])
