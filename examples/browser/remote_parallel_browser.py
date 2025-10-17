import asyncio
import os
from typing import Any

from browser_use_sdk import AsyncBrowserUse


async def main():
	# Initialize the client
	api_key = os.environ.get('BROWSER_USE_API_KEY', 'test-token')
	client = AsyncBrowserUse(api_key=api_key)

	# Create tasks directly - sessions are managed automatically
	print('Creating and running 3 agent tasks in parallel...')

	tasks = [
		client.tasks.create_task(
			task='Search for "browser automation" on Google',
		),
		client.tasks.create_task(
			task='Search for "AI agents" on DuckDuckGo',
		),
		client.tasks.create_task(
			task='Visit Wikipedia and search for "web scraping"',
		),
	]

	# Wait for all tasks to be created
	created_tasks = await asyncio.gather(*tasks)

	print('Tasks created:')
	for i, task in enumerate(created_tasks):
		print(f'  Task {i}: ID={task.id}')

	# Run all tasks in parallel by calling complete() on each
	print('\nRunning all agent tasks in parallel...')
	results = await asyncio.gather(*[task.complete() for task in created_tasks], return_exceptions=True)

	print('All tasks completed!')
	for i, result in enumerate(results):
		if isinstance(result, Exception):
			print(f'Task {i} failed: {result}')
		elif hasattr(result, 'output'):
			output: Any = getattr(result, 'output', None)
			print(f'Task {i} output: {output}')
		else:
			print(f'Task {i} returned unexpected result: {result}')

	print('🎉 All agents completed!')


if __name__ == '__main__':
	asyncio.run(main())
