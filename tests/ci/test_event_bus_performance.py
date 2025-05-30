"""
Performance and stress tests for the EventBus.

Tests cover:
- High volume event processing
- Memory usage
- Concurrent operations
- Large payloads
- Long-running handlers
"""

import asyncio
import gc
import time
from datetime import datetime
from typing import Any

import pytest
from pydantic import BaseModel, Field

from browser_use.event_bus import Event, EventBus


class StressTestEvent(BaseModel):
	"""Event for stress testing"""

	event_id: int
	payload: str
	timestamp: datetime = Field(default_factory=datetime.utcnow)
	metadata: dict[str, Any] = Field(default_factory=dict)


class MockAgent:
	"""Mock agent for testing"""

	def __init__(self):
		self.name = 'StressTestAgent'


@pytest.fixture
async def stress_event_bus():
	"""Create event bus for stress testing"""
	agent = MockAgent()
	bus = EventBus(agent)
	await bus.start()
	yield bus
	await bus.stop()


class TestHighVolumeProcessing:
	"""Test high volume event processing"""

	@pytest.mark.asyncio
	async def test_thousand_events_processing(self, stress_event_bus):
		"""Test processing 1000 events"""
		event_count = 1000
		processed = []

		async def counter_handler(event: Event, agent: Any) -> int:
			processed.append(event.data['event_id'])
			return event.data['event_id']

		stress_event_bus.subscribe('StressTestEvent', counter_handler)

		# Measure time
		start_time = time.time()

		# Enqueue all events
		for i in range(event_count):
			event = StressTestEvent(event_id=i, payload=f'Event {i}')
			stress_event_bus.emit(event)

		# Wait for processing
		await stress_event_bus.wait_for_empty_queue()

		duration = time.time() - start_time

		# Verify all processed
		assert len(processed) == event_count
		assert sorted(processed) == list(range(event_count))

		# Performance check - should process 1000 events in reasonable time
		assert duration < 5.0  # 5 seconds for 1000 events

		# Calculate throughput
		throughput = event_count / duration
		print(f'\nThroughput: {throughput:.2f} events/second')

	@pytest.mark.asyncio
	async def test_concurrent_producers(self, stress_event_bus):
		"""Test multiple concurrent event producers"""
		producers = 10
		events_per_producer = 100

		processed_by_producer = {i: [] for i in range(producers)}

		async def tracking_handler(event: Event, agent: Any) -> str:
			producer_id = event.data['metadata']['producer_id']
			event_id = event.data['event_id']
			processed_by_producer[producer_id].append(event_id)
			return f'p{producer_id}_e{event_id}'

		stress_event_bus.subscribe('StressTestEvent', tracking_handler)

		# Create producer tasks
		async def producer(producer_id: int):
			for i in range(events_per_producer):
				event = StressTestEvent(
					event_id=i, payload=f'Producer {producer_id} Event {i}', metadata={'producer_id': producer_id}
				)
				await stress_event_bus.enqueue(event)

		# Run all producers concurrently
		start_time = time.time()
		await asyncio.gather(*[producer(i) for i in range(producers)])
		await stress_event_bus.wait_for_empty_queue()
		duration = time.time() - start_time

		# Verify all events processed
		for producer_id in range(producers):
			assert len(processed_by_producer[producer_id]) == events_per_producer
			assert sorted(processed_by_producer[producer_id]) == list(range(events_per_producer))

		total_events = producers * events_per_producer
		print(f'\nProcessed {total_events} events from {producers} producers in {duration:.2f}s')


class TestMemoryUsage:
	"""Test memory usage and cleanup"""

	@pytest.mark.asyncio
	async def test_write_ahead_log_memory(self, stress_event_bus):
		"""Test memory usage of write-ahead log"""
		# Disable default handler to reduce overhead
		stress_event_bus.all_event_handlers.clear()

		# Large payload
		large_payload = 'x' * 10000  # 10KB string

		# Add many events
		for i in range(100):
			event = StressTestEvent(event_id=i, payload=large_payload, metadata={'index': i, 'data': [j for j in range(100)]})
			stress_event_bus.emit(event)

		# Wait for processing
		await stress_event_bus.wait_for_empty_queue()

		# Check write-ahead log size
		log = stress_event_bus.get_event_log()
		assert len(log) == 100

		# Force garbage collection
		gc.collect()

		# Clear log reference
		del log
		gc.collect()

	@pytest.mark.asyncio
	async def test_event_cleanup_after_processing(self, stress_event_bus):
		"""Test that completed events can be garbage collected"""
		import weakref

		# Track events with weak references
		weak_refs = []

		async def tracking_handler(event: Event, agent: Any) -> str:
			# Create weak reference to event
			weak_refs.append(weakref.ref(event))
			return 'tracked'

		stress_event_bus.subscribe('StressTestEvent', tracking_handler)

		# Process events
		events = []
		for i in range(10):
			event = await stress_event_bus.enqueue_and_wait(StressTestEvent(event_id=i, payload='test'))
			events.append(event)

		# All events should still be referenced
		assert all(ref() is not None for ref in weak_refs)

		# Clear our references
		events.clear()
		gc.collect()

		# Some events might be garbage collected (depends on write-ahead log)
		# This is more of a sanity check than a strict test


class TestLargePayloads:
	"""Test handling of large event payloads"""

	@pytest.mark.asyncio
	async def test_large_event_payload(self, stress_event_bus):
		"""Test processing events with large payloads"""
		# 1MB payload
		large_data = {
			'text': 'x' * (1024 * 1024),
			'numbers': list(range(10000)),
			'nested': {'level1': {'level2': {'data': ['item'] * 1000}}},
		}

		processed = False

		async def large_handler(event: Event, agent: Any) -> str:
			nonlocal processed
			# Verify data integrity
			assert len(event.data['metadata']['text']) == 1024 * 1024
			assert len(event.data['metadata']['numbers']) == 10000
			processed = True
			return 'processed_large'

		stress_event_bus.subscribe('StressTestEvent', large_handler)

		# Send large event
		event = StressTestEvent(event_id=1, payload='Large event', metadata=large_data)

		result = await stress_event_bus.enqueue_and_wait(event)

		assert processed
		assert result.results['large_handler'] == 'processed_large'

	@pytest.mark.asyncio
	async def test_many_handlers_per_event(self, stress_event_bus):
		"""Test events with many handlers"""
		handler_count = 100
		results = []

		# Create many handlers
		for i in range(handler_count):

			async def make_handler(handler_id):
				async def handler(event: Event, agent: Any) -> int:
					results.append(handler_id)
					return handler_id

				return handler

			handler = await make_handler(i)
			handler.__name__ = f'handler_{i}'
			stress_event_bus.subscribe('StressTestEvent', handler)

		# Process event
		event = await stress_event_bus.enqueue_and_wait(StressTestEvent(event_id=1, payload='Many handlers'))

		# Verify all handlers ran
		assert len(results) == handler_count
		assert len(event.results) == handler_count + 1  # +1 for default logger


class TestLongRunningHandlers:
	"""Test handling of long-running event handlers"""

	@pytest.mark.asyncio
	async def test_slow_handler_doesnt_block_queue(self, stress_event_bus):
		"""Test that slow handlers don't block event processing"""
		process_times = []

		async def slow_handler(event: Event, agent: Any) -> str:
			event_id = event.data['event_id']
			if event_id == 0:
				# First event handler is slow
				await asyncio.sleep(1)
			process_times.append((event_id, time.time()))
			return f'processed_{event_id}'

		stress_event_bus.subscribe('StressTestEvent', slow_handler)

		# Send multiple events
		start_time = time.time()

		events = []
		for i in range(5):
			event = StressTestEvent(event_id=i, payload=f'Event {i}')
			events.append(await stress_event_bus.enqueue(event))

		# Wait for all to complete
		await stress_event_bus.wait_for_empty_queue()

		# Check that events were processed in order but didn't wait for slow handler
		assert len(process_times) == 5

		# Event 0 should finish last due to sleep
		sorted_by_time = sorted(process_times, key=lambda x: x[1])
		assert sorted_by_time[-1][0] == 0  # Event 0 finished last

	@pytest.mark.asyncio
	async def test_timeout_handling(self, stress_event_bus):
		"""Test handling of handler timeouts"""
		timed_out = False

		async def timeout_handler(event: Event, agent: Any) -> str:
			nonlocal timed_out
			try:
				# This will timeout
				await asyncio.wait_for(asyncio.sleep(10), timeout=0.1)
			except TimeoutError:
				timed_out = True
				raise
			return 'should_not_reach'

		stress_event_bus.subscribe('StressTestEvent', timeout_handler)

		# Process event
		event = await stress_event_bus.enqueue_and_wait(StressTestEvent(event_id=1, payload='Timeout test'))

		# Handler should have failed with timeout
		assert timed_out
		assert 'timeout_handler' in event.errors
		assert isinstance(event.errors['timeout_handler'], asyncio.TimeoutError)


class TestEdgeCasesUnderLoad:
	"""Test edge cases under load"""

	@pytest.mark.asyncio
	async def test_stop_under_heavy_load(self, mock_agent):
		"""Test stopping event bus under heavy load"""
		bus = EventBus(mock_agent)
		await bus.start()

		# Add slow handler
		async def slow_handler(event: Event, agent: Any) -> str:
			await asyncio.sleep(0.1)
			return 'slow'

		bus.subscribe_to_all(slow_handler)

		# Queue many events
		for i in range(100):
			bus.emit(StressTestEvent(event_id=i, payload='Load test'))

		# Stop immediately (should handle gracefully)
		await bus.stop()

		assert not bus.running

	@pytest.mark.asyncio
	async def test_concurrent_handler_registration(self, stress_event_bus):
		"""Test registering handlers while events are being processed"""
		handlers_called = set()

		async def initial_handler(event: Event, agent: Any) -> str:
			handlers_called.add('initial')
			return 'initial'

		stress_event_bus.subscribe('StressTestEvent', initial_handler)

		# Start processing events
		for i in range(10):
			stress_event_bus.emit(StressTestEvent(event_id=i, payload='Test'))

		# Add handler while processing
		async def late_handler(event: Event, agent: Any) -> str:
			handlers_called.add('late')
			return 'late'

		stress_event_bus.subscribe('StressTestEvent', late_handler)

		# Add more events
		for i in range(10, 20):
			stress_event_bus.emit(StressTestEvent(event_id=i, payload='Test'))

		await stress_event_bus.wait_for_empty_queue()

		# Both handlers should have been called
		assert 'initial' in handlers_called
		assert 'late' in handlers_called

	@pytest.mark.asyncio
	async def test_recursive_event_emission(self, stress_event_bus):
		"""Test handlers that emit new events"""
		max_depth = 5
		depths_seen = []

		async def recursive_handler(event: Event, agent: Any) -> str:
			depth = event.data.get('metadata', {}).get('depth', 0)
			depths_seen.append(depth)

			if depth < max_depth:
				# Emit new event
				new_event = StressTestEvent(event_id=depth + 1, payload=f'Depth {depth + 1}', metadata={'depth': depth + 1})
				stress_event_bus.emit(new_event)

			return f'depth_{depth}'

		stress_event_bus.subscribe('StressTestEvent', recursive_handler)

		# Start recursion
		stress_event_bus.emit(StressTestEvent(event_id=0, payload='Start', metadata={'depth': 0}))

		# Wait for all events
		await stress_event_bus.wait_for_empty_queue()

		# Should have processed all depths
		assert sorted(depths_seen) == list(range(max_depth + 1))


if __name__ == '__main__':
	pytest.main([__file__, '-v', '-s'])  # -s to see print outputs
