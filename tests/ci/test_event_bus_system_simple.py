"""
Simplified test suite for the EventBus system that doesn't require full Agent initialization.

This focuses on testing the event bus functionality itself and event emissions.
"""

import asyncio
import json
import time
from typing import Any

import anyio
import pytest

from browser_use.event_bus import (
	ErrorTrackedEvent,
	Event,
	EventBus,
	OutputFileGeneratedEvent,
	PerformanceMetricEvent,
	SessionBrowserDataUpdatedEvent,
	SessionBrowserStateUpdatedEvent,
	SessionStartedEvent,
	SessionStoppedEvent,
	StepCreatedEvent,
	StepExecutedEvent,
	TaskAnalyticsEvent,
	TaskCompletedEvent,
	TaskPausedEvent,
	TaskResumedEvent,
	TaskStartedEvent,
	TaskStoppedEvent,
)


class MockAgent:
	"""Mock agent for testing event bus"""

	def __init__(self):
		self.name = 'TestAgent'
		self.task = 'Test task'
		self.model_name = 'mock-model'


@pytest.fixture
async def event_bus():
	"""Create an event bus for testing"""
	agent = MockAgent()
	bus = EventBus(agent)
	await bus.start()
	yield bus
	await bus.stop()


@pytest.fixture
async def event_collector():
	"""Fixture to collect all events emitted during tests"""
	events = []

	async def collector(event: Event, agent: Any) -> dict:
		events.append({'event_type': event.event_type, 'event': event, 'timestamp': time.time()})
		return {'collected': True}

	collector.events = events
	return collector


class TestEventBusCore:
	"""Test core EventBus functionality"""

	async def test_event_emission_and_collection(self, event_bus, event_collector):
		"""Test basic event emission and collection"""
		# Subscribe collector
		event_bus.subscribe_to_all(event_collector)

		# Emit various events
		events = [
			SessionStartedEvent(session_id='s1', user_id='u1'),
			TaskStartedEvent(session_id='s1', task_description='Test task'),
			StepCreatedEvent(
				step_id='step1',
				agent_task_id='t1',
				step=1,
				evaluation_previous_goal='',
				memory='',
				next_goal='',
				actions=[],
				screenshot_url='',
				url='http://example.com',
			),
			TaskCompletedEvent(task_id='t1', session_id='s1', duration_seconds=10.0, total_steps=1),
			SessionStoppedEvent(session_id='s1', total_duration_seconds=10.5),
		]

		for event in events:
			await event_bus.enqueue(event)

		# Wait for processing
		await event_bus.wait_for_empty_queue()

		# Verify all events collected (includes default logger handler)
		assert len(event_collector.events) >= len(events)
		collected_types = [e['event_type'] for e in event_collector.events]
		assert 'SessionStartedEvent' in collected_types
		assert 'TaskStartedEvent' in collected_types
		assert 'StepCreatedEvent' in collected_types
		assert 'TaskCompletedEvent' in collected_types
		assert 'SessionStoppedEvent' in collected_types

	async def test_event_handler_subscription(self, event_bus):
		"""Test event handler subscription patterns"""
		session_events = []
		task_events = []
		all_events = []

		async def session_handler(event: Event, agent: Any) -> dict:
			session_events.append(event)
			return {'session_handled': True}

		async def task_handler(event: Event, agent: Any) -> dict:
			task_events.append(event)
			return {'task_handled': True}

		async def all_handler(event: Event, agent: Any) -> dict:
			all_events.append(event)
			return {'all_handled': True}

		# Subscribe to specific event types
		event_bus.subscribe('SessionStartedEvent', session_handler)
		event_bus.subscribe('SessionStoppedEvent', session_handler)
		event_bus.subscribe('TaskStartedEvent', task_handler)
		event_bus.subscribe('TaskCompletedEvent', task_handler)
		event_bus.subscribe_to_all(all_handler)

		# Emit events
		session_start = SessionStartedEvent(session_id='s1', user_id='u1')
		task_start = TaskStartedEvent(session_id='s1', task_description='Test')
		task_complete = TaskCompletedEvent(task_id='t1', session_id='s1', duration_seconds=5.0, total_steps=1)
		session_stop = SessionStoppedEvent(session_id='s1', total_duration_seconds=5.0)

		for event in [session_start, task_start, task_complete, session_stop]:
			await event_bus.enqueue_and_wait(event)

		# Verify handlers called correctly
		assert len(session_events) == 2
		assert len(task_events) == 2
		assert len(all_events) == 4

	async def test_event_serialization(self, event_bus, tmp_path):
		"""Test event serialization to JSON"""
		# Emit various cloud events
		events = [
			SessionStartedEvent(
				session_id='test_session', user_id='test_user', browser_type='chrome', window_width=1920, window_height=1080
			),
			SessionBrowserStateUpdatedEvent(
				session_id='test_session',
				current_url='https://example.com',
				current_title='Example Page',
				active_tab_id=0,
				total_tabs=1,
				tabs_info=[{'id': 0, 'url': 'https://example.com'}],
			),
			StepExecutedEvent(
				task_id='test_task',
				session_id='test_session',
				step_number=1,
				action_type='click',
				action_params={'index': 1},
				evaluation_previous_goal='Start',
				memory='No memory',
				next_goal='Click button',
				url_before='https://example.com',
				url_after='https://example.com',
				duration_ms=500.0,
				model_name='mock-model',
			),
			ErrorTrackedEvent(
				session_id='test_session',
				task_id='test_task',
				error_type='TestError',
				error_message='This is a test error',
				severity='medium',
				recoverable=True,
			),
			PerformanceMetricEvent(
				session_id='test_session',
				metric_name='step_duration',
				metric_value=0.5,
				metric_unit='seconds',
				tags={'step': '1'},
			),
			TaskAnalyticsEvent(
				task_id='test_task',
				session_id='test_session',
				success_rate=0.9,
				steps_to_completion=10,
				retry_count=1,
				avg_step_duration_ms=500.0,
				total_duration_seconds=5.0,
				idle_time_seconds=0.5,
				total_tokens=1000,
				total_cost_usd=0.01,
				cost_per_step_usd=0.001,
				pages_visited=3,
				unique_domains=2,
				total_clicks=5,
				total_form_fills=2,
				screenshots_taken=10,
				data_extracted_bytes=1024,
				files_generated=1,
				errors_encountered=1,
			),
		]

		for event in events:
			await event_bus.enqueue(event)

		# Wait for processing
		await event_bus.wait_for_empty_queue()

		# Serialize to file
		event_file = tmp_path / 'events.json'
		await event_bus.serialize_events_to_file(str(event_file))

		# Load and verify
		async with await anyio.open_file(event_file) as f:
			content = await f.read()
			loaded_events = json.loads(content)

		assert len(loaded_events) >= len(events)

		# Check all event types present
		event_types = [e['event_type'] for e in loaded_events]
		assert 'SessionStartedEvent' in event_types
		assert 'SessionBrowserStateUpdatedEvent' in event_types
		assert 'StepExecutedEvent' in event_types
		assert 'ErrorTrackedEvent' in event_types
		assert 'PerformanceMetricEvent' in event_types
		assert 'TaskAnalyticsEvent' in event_types

		# Verify specific event data
		session_event = next(e for e in loaded_events if e['event_type'] == 'SessionStartedEvent')
		assert session_event['user_id'] == 'test_user'
		assert session_event['browser_type'] == 'chrome'

		analytics_event = next(e for e in loaded_events if e['event_type'] == 'TaskAnalyticsEvent')
		assert analytics_event['success_rate'] == 0.9
		assert analytics_event['total_clicks'] == 5

	async def test_event_completion_tracking(self, event_bus):
		"""Test event completion tracking functionality"""
		results = []

		async def slow_handler(event: Event, agent: Any) -> dict:
			await asyncio.sleep(0.1)
			results.append(event.event_type)
			return {'processed': True, 'duration': 0.1}

		event_bus.subscribe_to_all(slow_handler)

		# Emit event without waiting
		event = TaskStartedEvent(session_id='s1', task_description='Test')
		event_obj = await event_bus.enqueue(event)

		# Event should not be completed yet
		assert event_obj.completed_at is None

		# Wait for completion
		await event_obj.wait_for_completion()

		# Now should be completed
		assert event_obj.completed_at is not None
		assert len(results) == 1
		assert event_obj.results['slow_handler']['processed'] is True

	async def test_error_handling_in_handlers(self, event_bus):
		"""Test that handler errors are captured properly"""
		success_count = 0

		async def failing_handler(event: Event, agent: Any) -> dict:
			raise ValueError('Handler failed!')

		async def success_handler(event: Event, agent: Any) -> dict:
			nonlocal success_count
			success_count += 1
			return {'success': True}

		event_bus.subscribe_to_all(failing_handler)
		event_bus.subscribe_to_all(success_handler)

		# Emit event and wait
		event = ErrorTrackedEvent(error_type='TestError', error_message='Test')
		result = await event_bus.enqueue_and_wait(event)

		# Check results
		assert success_count == 1
		assert 'failing_handler' in result.errors
		assert isinstance(result.errors['failing_handler'], ValueError)
		assert 'success_handler' in result.results
		assert result.results['success_handler']['success'] is True

	async def test_fifo_ordering(self, event_bus):
		"""Test that events are processed in FIFO order"""
		processed_order = []

		async def order_handler(event: Event, agent: Any) -> dict:
			# For base Event class, data is in the data field
			if hasattr(event, 'order_id'):
				processed_order.append(event.order_id)
			else:
				processed_order.append(event.data.get('order', -1))
			return {'processed': True}

		event_bus.subscribe_to_all(order_handler)

		# Emit events with order markers
		for i in range(10):
			event = Event(data={'order': i})
			await event_bus.enqueue(event)

		# Wait for all to process
		await event_bus.wait_for_empty_queue()

		# Check FIFO order maintained
		assert processed_order == list(range(10))

	async def test_high_volume_performance(self, event_bus):
		"""Test performance with high volume of events"""
		event_count = 100
		processed_count = 0

		async def counter_handler(event: Event, agent: Any) -> dict:
			nonlocal processed_count
			processed_count += 1
			return {'counted': True}

		event_bus.subscribe_to_all(counter_handler)

		# Measure time
		start_time = time.time()

		# Emit many events
		for i in range(event_count):
			event = PerformanceMetricEvent(session_id='test', metric_name=f'metric_{i}', metric_value=i, metric_unit='test')
			await event_bus.enqueue(event)

		# Wait for processing
		await event_bus.wait_for_empty_queue()
		duration = time.time() - start_time

		# Verify all processed (we should have at least event_count, may have more due to default handlers)
		assert processed_count >= event_count

		# Check performance
		throughput = event_count / duration
		print(f'\nProcessed {event_count} events in {duration:.2f}s ({throughput:.0f} events/sec)')
		assert duration < 5.0  # Should handle 100 events in under 5 seconds


class TestCloudEvents:
	"""Test cloud event specific functionality"""

	async def test_all_cloud_events_instantiable(self):
		"""Test that all cloud events can be instantiated with minimal data"""
		# Session events
		SessionStartedEvent(session_id='s1', user_id='u1')
		SessionStoppedEvent(session_id='s1', total_duration_seconds=1.0)
		SessionBrowserStateUpdatedEvent(session_id='s1', current_url='http://test', active_tab_id=0, total_tabs=1)
		SessionBrowserDataUpdatedEvent(session_id='s1', browser_session_data={})

		# Task events
		TaskStartedEvent(session_id='s1', task_description='test')
		TaskCompletedEvent(task_id='t1', session_id='s1', duration_seconds=1.0, total_steps=1)
		TaskPausedEvent(task_id='t1', session_id='s1')
		TaskResumedEvent(task_id='t1', session_id='s1')
		TaskStoppedEvent(task_id='t1')
		TaskAnalyticsEvent(
			task_id='t1',
			session_id='s1',
			success_rate=1.0,
			steps_to_completion=1,
			retry_count=0,
			avg_step_duration_ms=100.0,
			total_duration_seconds=1.0,
			idle_time_seconds=0.0,
			total_tokens=0,
			total_cost_usd=0.0,
			cost_per_step_usd=0.0,
			pages_visited=1,
			unique_domains=1,
			total_clicks=0,
			total_form_fills=0,
			screenshots_taken=1,
			data_extracted_bytes=0,
			files_generated=0,
			errors_encountered=0,
		)

		# Step events
		StepCreatedEvent(
			step_id='s1',
			agent_task_id='t1',
			step=1,
			evaluation_previous_goal='',
			memory='',
			next_goal='',
			actions=[],
			screenshot_url='',
			url='',
		)
		StepExecutedEvent(
			task_id='t1',
			session_id='s1',
			step_number=1,
			action_type='test',
			evaluation_previous_goal='',
			memory='',
			next_goal='',
			url_before='',
			url_after='',
			duration_ms=100.0,
			model_name='test',
		)

		# Other events
		ErrorTrackedEvent(error_type='test', error_message='test')
		PerformanceMetricEvent(session_id='s1', metric_name='test', metric_value=1.0, metric_unit='test')
		OutputFileGeneratedEvent(
			task_id='t1', session_id='s1', filename='test', mime_type='test', size_bytes=0, storage_path='test'
		)

	async def test_event_type_derivation(self):
		"""Test that event_type is properly derived from class name"""
		events = [
			(SessionStartedEvent(session_id='s1', user_id='u1'), 'SessionStartedEvent'),
			(TaskStartedEvent(session_id='s1', task_description='test'), 'TaskStartedEvent'),
			(
				StepCreatedEvent(
					step_id='s1',
					agent_task_id='t1',
					step=1,
					evaluation_previous_goal='',
					memory='',
					next_goal='',
					actions=[],
					screenshot_url='',
					url='',
				),
				'StepCreatedEvent',
			),
			(ErrorTrackedEvent(error_type='test', error_message='test'), 'ErrorTrackedEvent'),
		]

		for event, expected_type in events:
			assert event.event_type == expected_type

			# Also check serialization
			serialized = event.model_dump()
			assert serialized['event_type'] == expected_type

	async def test_cloud_event_handler_pattern(self, event_bus):
		"""Test the cloud handler pattern for syncing events"""
		cloud_results = {}

		async def cloud_sync_handler(event: Event, agent: Any) -> dict:
			"""Simulate cloud sync handler"""
			event_type = event.event_type

			if event_type == 'SessionStartedEvent':
				cloud_results['session'] = {'id': event.session_id, 'user': event.user_id, 'synced': True}
				return {'cloud_id': f'cloud_{event.session_id}', 'synced': True}

			elif event_type == 'TaskStartedEvent':
				cloud_results['task'] = {'session_id': event.session_id, 'description': event.task_description, 'synced': True}
				return {'cloud_id': f'cloud_task_{event.task_id}', 'synced': True}

			elif event_type == 'StepExecutedEvent':
				cloud_results['steps'] = cloud_results.get('steps', [])
				cloud_results['steps'].append({'step': event.step_number, 'action': event.action_type, 'synced': True})
				return {'cloud_id': f'cloud_step_{event.step_id}', 'synced': True}

			return {'synced': False}

		# Subscribe handler to specific events
		for event_type in ['SessionStartedEvent', 'TaskStartedEvent', 'StepExecutedEvent']:
			event_bus.subscribe(event_type, cloud_sync_handler)

		# Simulate a workflow
		session_event = SessionStartedEvent(session_id='s123', user_id='u456')
		task_event = TaskStartedEvent(session_id='s123', task_description='Test workflow')
		step_event = StepExecutedEvent(
			task_id='t789',
			session_id='s123',
			step_number=1,
			action_type='click',
			evaluation_previous_goal='',
			memory='',
			next_goal='',
			url_before='http://example.com',
			url_after='http://example.com',
			duration_ms=100.0,
			model_name='mock',
		)

		# Process events
		for event in [session_event, task_event, step_event]:
			result = await event_bus.enqueue_and_wait(event)
			assert 'cloud_sync_handler' in result.results
			assert result.results['cloud_sync_handler']['synced'] is True

		# Verify cloud results
		assert 'session' in cloud_results
		assert cloud_results['session']['id'] == 's123'
		assert 'task' in cloud_results
		assert cloud_results['task']['description'] == 'Test workflow'
		assert 'steps' in cloud_results
		assert len(cloud_results['steps']) == 1
		assert cloud_results['steps'][0]['action'] == 'click'


if __name__ == '__main__':
	pytest.main([__file__, '-v', '-s'])
