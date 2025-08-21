"""
Cloud Example 2: Ultra-Fast Mode with Gemini Flash ⚡
====================================================

This example demonstrates the fastest and most cost-effective configuration:
- Gemini 2.5 Flash model ($0.01 per step)
- No proxy (faster execution, but no captcha solving)
- No element highlighting (better performance)
- Optimized viewport size
- Maximum speed configuration

Perfect for: Quick content generation, humor tasks, fast web scraping

Cost: ~$0.03 (1 task + 2-3 steps with Gemini Flash)
Speed: 2-3x faster than default configuration
Fun Factor: 💯 (Creates hilarious tech commentary)
"""

import argparse
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

	raise RuntimeError('Unexpected error in retry logic')


def create_fast_task(instructions: str) -> str:
	"""
	Create a browser automation task optimized for speed and cost.

	Args:
	    instructions: Natural language description of what the agent should do

	Returns:
	    task_id: Unique identifier for the created task
	"""
	print(f'⚡ Creating FAST task: {instructions}')

	# Ultra-fast configuration
	payload = {
		'task': instructions,
		# Model: Fastest and cheapest
		'llm_model': 'gemini-2.5-flash',
		# Performance optimizations
		'use_proxy': False,  # No proxy = faster execution
		'highlight_elements': False,  # No highlighting = better performance
		'use_adblock': True,  # Block ads for faster loading
		# Viewport optimization (smaller = faster)
		'browser_viewport_width': 1024,
		'browser_viewport_height': 768,
		# Cost control
		'max_agent_steps': 25,  # Reasonable limit for fast tasks
		# Enable sharing for viewing execution
		'enable_public_share': True,  # Get shareable URLs
		# Optional: Speed up with domain restrictions
		# "allowed_domains": ["google.com", "*.google.com"]
	}

	response = _request_with_retry('post', f'{BASE_URL}/run-task', headers=HEADERS, json=payload)

	task_id = response.json()['id']
	print(f'✅ Fast task created with ID: {task_id}')
	print('⚡ Configuration: Gemini Flash + No Proxy + No Highlighting')
	return task_id


def monitor_fast_task(task_id: str) -> dict[str, Any]:
	"""
	Monitor task with optimized polling for fast execution.

	Args:
	    task_id: The task to monitor

	Returns:
	    Complete task details with output
	"""
	print(f'🚀 Fast monitoring task {task_id}...')

	start_time = time.time()
	step_count = 0
	last_step_time = start_time

	# Faster polling for quick tasks
	poll_interval = 1  # Check every second for fast tasks

	while True:
		response = _request_with_retry('get', f'{BASE_URL}/task/{task_id}', headers=HEADERS)
		details = response.json()
		status = details['status']

		# Show progress with timing
		current_steps = len(details.get('steps', []))
		elapsed = time.time() - start_time

		# Build status message
		if current_steps > step_count:
			step_time = time.time() - last_step_time
			last_step_time = time.time()
			step_count = current_steps
			step_msg = f'🔥 Step {current_steps} | ⚡ {step_time:.1f}s | Total: {elapsed:.1f}s'
		else:
			if status == 'running':
				step_msg = f'🚀 Step {current_steps} | ⏱️  {elapsed:.1f}s | Fast processing...'
			else:
				step_msg = f'🚀 Step {current_steps} | ⏱️  {elapsed:.1f}s | Status: {status}'

		# Clear line and show progress
		print(f'\r{step_msg:<80}', end='', flush=True)

		# Check completion
		if status == 'finished':
			total_time = time.time() - start_time
			if current_steps > 0:
				avg_msg = f'⚡ Average: {total_time / current_steps:.1f}s per step'
			else:
				avg_msg = '⚡ No steps recorded'
			print(f'\r🏁 Task completed in {total_time:.1f}s! {avg_msg}' + ' ' * 20)
			return details

		elif status in ['failed', 'stopped']:
			print(f'\r❌ Task {status} after {elapsed:.1f}s' + ' ' * 30)
			return details

		time.sleep(poll_interval)


def run_speed_comparison():
	"""Run multiple tasks to compare speed vs accuracy."""
	print('\n🏃‍♂️ Speed Comparison Demo')
	print('=' * 40)

	tasks = [
		'Go to ProductHunt and roast the top product like a sarcastic tech reviewer',
		'Visit Reddit r/ProgrammerHumor and summarize the top post as a dramatic news story',
		"Check GitHub trending and write a conspiracy theory about why everyone's switching to Rust",
	]

	results = []

	for i, task in enumerate(tasks, 1):
		print(f'\n📝 Fast Task {i}/{len(tasks)}')
		print(f'Task: {task}')

		start = time.time()
		task_id = create_fast_task(task)
		result = monitor_fast_task(task_id)
		end = time.time()

		results.append(
			{
				'task': task,
				'duration': end - start,
				'steps': len(result.get('steps', [])),
				'status': result['status'],
				'output': result.get('output', '')[:100] + '...' if result.get('output') else 'No output',
			}
		)

	# Summary
	print('\n📊 Speed Summary')
	print('=' * 50)
	total_time = sum(r['duration'] for r in results)
	total_steps = sum(r['steps'] for r in results)

	for i, result in enumerate(results, 1):
		print(f'Task {i}: {result["duration"]:.1f}s ({result["steps"]} steps) - {result["status"]}')

	print(f'\n⚡ Total time: {total_time:.1f}s')
	print(f'🔥 Average per task: {total_time / len(results):.1f}s')
	if total_steps > 0:
		print(f'💨 Average per step: {total_time / total_steps:.1f}s')
	else:
		print('💨 Average per step: N/A (no steps recorded)')


def main():
	"""Demonstrate ultra-fast cloud automation."""
	print('⚡ Browser Use Cloud - Ultra-Fast Mode with Gemini Flash')
	print('=' * 60)

	print('🎯 Configuration Benefits:')
	print('• Gemini Flash: $0.01 per step (cheapest)')
	print('• No proxy: 30% faster execution')
	print('• No highlighting: Better performance')
	print('• Optimized viewport: Faster rendering')

	try:
		# Single fast task
		print('\n🚀 Single Fast Task Demo')
		print('-' * 30)

		task = """
        Go to Hacker News (news.ycombinator.com) and get the top 3 articles from the front page.
        
        Then, write a funny tech news segment in the style of Fireship YouTube channel:
        - Be sarcastic and witty about tech trends
        - Use developer humor and memes  
        - Make fun of common programming struggles
        - Include phrases like "And yes, it runs on JavaScript" or "Plot twist: it's written in Rust"
        - Keep it under 250 words but make it entertaining
        - Structure it like a news anchor delivering breaking tech news
        
        Make each story sound dramatic but also hilarious, like you're reporting on the most important events in human history.
        """
		task_id = create_fast_task(task)
		result = monitor_fast_task(task_id)

		print(f'\n📊 Result: {result.get("output", "No output")}')

		# Show execution URLs
		if result.get('live_url'):
			print(f'\n🔗 Live Preview: {result["live_url"]}')
		if result.get('public_share_url'):
			print(f'🌐 Share URL: {result["public_share_url"]}')
		elif result.get('share_url'):
			print(f'🌐 Share URL: {result["share_url"]}')

		# Optional: Run speed comparison with --compare flag
		parser = argparse.ArgumentParser(description='Fast mode demo with Gemini Flash')
		parser.add_argument('--compare', action='store_true', help='Run speed comparison with 3 tasks')
		args = parser.parse_args()

		if args.compare:
			print('\n🏃‍♂️ Running speed comparison...')
			run_speed_comparison()

	except requests.exceptions.RequestException as e:
		print(f'❌ API Error: {e}')
	except Exception as e:
		print(f'❌ Error: {e}')


if __name__ == '__main__':
	main()
