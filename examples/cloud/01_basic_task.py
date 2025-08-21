"""
Cloud Example 1: Your First Browser Use Cloud Task
==================================================

This example demonstrates the most basic Browser Use Cloud functionality:
- Create a simple automation task
- Get the task ID
- Monitor completion
- Retrieve results

Perfect for first-time cloud users to understand the API basics.

Cost: ~$0.04 (1 task + 3 steps with GPT-4.1 mini)
"""

import os
import time
from typing import Any

import requests
from requests.exceptions import RequestException

# Configuration
API_KEY = os.getenv('BROWSER_USE_API_KEY')
if not API_KEY:
	raise ValueError('Please set BROWSER_USE_API_KEY environment variable')

BASE_URL = os.getenv('BROWSER_USE_BASE_URL', 'https://api.browser-use.com/api/v1')
TIMEOUT = int(os.getenv('BROWSER_USE_TIMEOUT', '30'))
HEADERS = {'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'}


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
	"""Make HTTP request with timeout and retry logic."""
	kwargs.setdefault('timeout', TIMEOUT)

	for attempt in range(3):
		try:
			response = requests.request(method, url, **kwargs)
			response.raise_for_status()
			return response
		except RequestException as e:
			if attempt == 2:  # Last attempt
				raise
			sleep_time = 2**attempt
			print(f'⚠️  Request failed (attempt {attempt + 1}/3), retrying in {sleep_time}s: {e}')
			time.sleep(sleep_time)

	# This line should never be reached, but satisfies type checker
	raise RuntimeError('Unexpected error in retry logic')


def create_task(instructions: str) -> str:
	"""
	Create a new browser automation task.

	Args:
	    instructions: Natural language description of what the agent should do

	Returns:
	    task_id: Unique identifier for the created task
	"""
	print(f'📝 Creating task: {instructions}')

	payload = {
		'task': instructions,
		'llm_model': 'gpt-4.1-mini',  # Cost-effective model
		'max_agent_steps': 10,  # Prevent runaway costs
		'enable_public_share': True,  # Enable shareable execution URLs
	}

	response = _request_with_retry('post', f'{BASE_URL}/run-task', headers=HEADERS, json=payload)

	task_id = response.json()['id']
	print(f'✅ Task created with ID: {task_id}')
	return task_id


def get_task_status(task_id: str) -> dict[str, Any]:
	"""Get the current status of a task."""
	response = _request_with_retry('get', f'{BASE_URL}/task/{task_id}/status', headers=HEADERS)
	return response.json()


def get_task_details(task_id: str) -> dict[str, Any]:
	"""Get full task details including steps and output."""
	response = _request_with_retry('get', f'{BASE_URL}/task/{task_id}', headers=HEADERS)
	return response.json()


def wait_for_completion(task_id: str, poll_interval: int = 3) -> dict[str, Any]:
	"""
	Wait for task completion and show progress.

	Args:
	    task_id: The task to monitor
	    poll_interval: How often to check status (seconds)

	Returns:
	    Complete task details with output
	"""
	print(f'⏳ Monitoring task {task_id}...')

	step_count = 0
	start_time = time.time()

	while True:
		details = get_task_details(task_id)
		status = details['status']
		current_steps = len(details.get('steps', []))
		elapsed = time.time() - start_time

		# Clear line and show current progress
		if current_steps > step_count:
			step_count = current_steps

		# Build status message
		if status == 'running':
			if current_steps > 0:
				status_msg = f'🔄 Step {current_steps} | ⏱️  {elapsed:.0f}s | 🤖 Agent working...'
			else:
				status_msg = f'🤖 Agent starting... | ⏱️  {elapsed:.0f}s'
		else:
			status_msg = f'🔄 Step {current_steps} | ⏱️  {elapsed:.0f}s | Status: {status}'

		# Clear line and print status
		print(f'\r{status_msg:<80}', end='', flush=True)

		# Check if finished
		if status == 'finished':
			print(f'\r✅ Task completed successfully! ({current_steps} steps in {elapsed:.1f}s)' + ' ' * 20)
			return details
		elif status in ['failed', 'stopped']:
			print(f'\r❌ Task {status} after {current_steps} steps' + ' ' * 30)
			return details

		time.sleep(poll_interval)


def main():
	"""Run a basic cloud automation task."""
	print('🚀 Browser Use Cloud - Basic Task Example')
	print('=' * 50)

	# Define a simple search task (using DuckDuckGo to avoid captchas)
	task_description = (
		"Go to DuckDuckGo and search for 'browser automation tools'. Tell me the top 3 results with their titles and URLs."
	)

	try:
		# Step 1: Create the task
		task_id = create_task(task_description)

		# Step 2: Wait for completion
		result = wait_for_completion(task_id)

		# Step 3: Display results
		print('\n📊 Results:')
		print('-' * 30)
		print(f'Status: {result["status"]}')
		print(f'Steps taken: {len(result.get("steps", []))}')

		if result.get('output'):
			print(f'Output: {result["output"]}')
		else:
			print('No output available')

		# Show share URLs for viewing execution
		if result.get('live_url'):
			print(f'\n🔗 Live Preview: {result["live_url"]}')
		if result.get('public_share_url'):
			print(f'🌐 Share URL: {result["public_share_url"]}')
		elif result.get('share_url'):
			print(f'🌐 Share URL: {result["share_url"]}')

		if not result.get('live_url') and not result.get('public_share_url') and not result.get('share_url'):
			print("\n💡 Tip: Add 'enable_public_share': True to task payload to get shareable URLs")

	except requests.exceptions.RequestException as e:
		print(f'❌ API Error: {e}')
	except Exception as e:
		print(f'❌ Error: {e}')


if __name__ == '__main__':
	main()
