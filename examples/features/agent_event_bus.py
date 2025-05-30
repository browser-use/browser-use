"""
Example of using the EventBus with browser-use Agent.

This example demonstrates:
1. Setting up event handlers for cloud sync
2. Tracking agent actions and performance
3. Serializing events for analysis
"""

import asyncio
import json
from pathlib import Path

import anyio
from langchain_openai import ChatOpenAI

from browser_use import Agent


# Example cloud sync handler
async def cloud_sync_handler(event, agent):
	"""Simulate syncing events to cloud backend"""
	event_type = event.event_type

	print(f'\n🌥️  Cloud Sync: {event_type}')

	if event_type == 'SessionStartedEvent':
		print(f'   Session ID: {event.session_id}')
		print(f'   User ID: {event.user_id}')
		print(f'   Browser Type: {event.browser_type}')
		# In real implementation, would POST to cloud API
		return {'cloud_id': 'cloud_session_123', 'synced': True}

	elif event_type == 'TaskStartedEvent':
		print(f'   Task: {event.task_description}')
		print(f'   Session ID: {event.session_id}')
		return {'cloud_id': 'cloud_task_456', 'synced': True}

	elif event_type == 'StepCreatedEvent':
		print(f'   Step #{event.step}')
		print(f'   Actions: {len(event.actions)}')
		return {'cloud_id': f'cloud_step_{event.step}', 'synced': True}

	elif event_type == 'TaskCompletedEvent':
		print(f'   Result: {event.result_summary[:50] if event.result_summary else "No output"}...')
		return {'cloud_id': 'cloud_complete_789', 'synced': True}

	return {'synced': False}


# Performance tracking handler
async def performance_tracker(event, agent):
	"""Track performance metrics"""
	if hasattr(event, 'started_at') and hasattr(event, 'completed_at'):
		if event.started_at and event.completed_at:
			duration = (event.completed_at - event.started_at).total_seconds()
			print(f'⏱️  {event.event_type} took {duration:.2f}s')
	return 'tracked'


async def main():
	# Create agent
	agent = Agent(
		task="Go to google.com and search for 'browser automation with AI'",
		llm=ChatOpenAI(model='gpt-4o-mini'),
	)

	# Subscribe handlers to specific events
	agent.event_bus.subscribe('SessionStartedEvent', cloud_sync_handler)
	agent.event_bus.subscribe('TaskStartedEvent', cloud_sync_handler)
	agent.event_bus.subscribe('StepCreatedEvent', cloud_sync_handler)
	agent.event_bus.subscribe('TaskCompletedEvent', cloud_sync_handler)

	# Subscribe performance tracker to all events
	agent.event_bus.subscribe_to_all(performance_tracker)

	# You can also use the decorator pattern
	@agent.event_bus.decorator('SessionStoppedEvent')
	async def on_session_stopped(event, agent):
		print('\n🛑 Session stopped, saving event log...')
		return 'handled'

	try:
		# Run the agent
		print('🚀 Starting agent with event tracking...\n')
		result = await agent.run(max_steps=3)

		# Get all events from the write-ahead log
		all_events = agent.event_bus.get_event_log()
		print(f'\n📊 Total events recorded: {len(all_events)}')

		# Group events by type
		event_types = {}
		for event in all_events:
			event_type = event.event_type
			event_types[event_type] = event_types.get(event_type, 0) + 1

		print('\n📈 Event Summary:')
		for event_type, count in event_types.items():
			print(f'   {event_type}: {count}')

		# Find events with errors
		error_events = [e for e in all_events if e.errors]
		if error_events:
			print(f'\n⚠️  Events with errors: {len(error_events)}')

		# Save events to file
		events_file = Path('agent_events.json')
		await agent.event_bus.serialize_events_to_file(events_file)
		print(f'\n💾 Events saved to {events_file}')

		# Example: Load and analyze specific events
		async with await anyio.open_file(events_file) as f:
			content = await f.read()
			saved_events = json.loads(content)

		# Find all step events
		step_events = [e for e in saved_events if e['event_type'] == 'StepCreatedEvent']
		print(f'\n🔍 Found {len(step_events)} step events')

		for i, step in enumerate(step_events):
			print(f'\n   Step {i + 1}:')
			print(f'   - URL: {step.get("url", "N/A")}')
			print(f'   - Actions: {step.get("actions", [])}')

			# Check if this step was synced to cloud
			if 'cloud_sync_handler' in step.get('results', {}):
				sync_result = step['results']['cloud_sync_handler']
				print(f'   - Cloud sync: {"✅" if sync_result.get("synced") else "❌"}')

	finally:
		# The event bus will be stopped automatically when agent closes
		pass


if __name__ == '__main__':
	asyncio.run(main())
