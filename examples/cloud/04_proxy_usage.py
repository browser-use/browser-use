"""
Cloud Example 4: Proxy Usage 🌍
===============================

This example demonstrates reliable proxy usage scenarios:
- Different country proxies for geo-restrictions
- IP address and location verification
- Region-specific content access (streaming, news)
- Search result localization by country
- Mobile/residential proxy benefits

Perfect for: Geo-restricted content, location testing, regional analysis

Cost: ~$0.08 (1 task + 6-8 steps with proxy enabled)
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


def create_task_with_proxy(instructions: str, country_code: str = 'us') -> str:
	"""
	Create a task with proxy enabled from a specific country.

	Args:
	    instructions: Task description
	    country_code: Proxy country ('us', 'fr', 'it', 'jp', 'au', 'de', 'fi', 'ca')

	Returns:
	    task_id: Unique identifier for the created task
	"""
	print(f'🌍 Creating task with {country_code.upper()} proxy')
	print(f'📝 Task: {instructions}')

	payload = {
		'task': instructions,
		'llm_model': 'gpt-4.1-mini',
		# Proxy configuration
		'use_proxy': True,  # Required for captcha solving
		'proxy_country_code': country_code,  # Choose proxy location
		# Standard settings
		'use_adblock': True,  # Block ads for faster loading
		'highlight_elements': True,  # Keep highlighting for visibility
		'max_agent_steps': 15,
		# Enable sharing for viewing execution
		'enable_public_share': True,  # Get shareable URLs
	}

	response = _request_with_retry('post', f'{BASE_URL}/run-task', headers=HEADERS, json=payload)

	task_id = response.json()['id']
	print(f'✅ Task created with {country_code.upper()} proxy: {task_id}')
	return task_id


def test_ip_location(country_code: str) -> dict[str, Any]:
	"""Test IP address and location detection with proxy."""
	task = """
    Go to whatismyipaddress.com and tell me:
    1. The detected IP address
    2. The detected country/location
    3. The ISP/organization
    4. Any other location details shown
    
    Please be specific about what you see on the page.
    """

	task_id = create_task_with_proxy(task, country_code)
	return wait_for_completion(task_id)


def test_geo_restricted_content(country_code: str) -> dict[str, Any]:
	"""Test access to geo-restricted content."""
	task = """
    Go to a major news website (like BBC, CNN, or local news) and check:
    1. What content is available 
    2. Any geo-restriction messages
    3. Local/regional content differences
    4. Language or currency preferences shown
    
    Note any differences from what you might expect.
    """

	task_id = create_task_with_proxy(task, country_code)
	return wait_for_completion(task_id)


def test_streaming_service_access(country_code: str) -> dict[str, Any]:
	"""Test access to region-specific streaming content."""
	task = """
    Go to a major streaming service website (like Netflix, YouTube, or BBC iPlayer) 
    and check what content or messaging appears.
    
    Report:
    1. What homepage content is shown
    2. Any geo-restriction messages or content differences
    3. Available content regions or language options
    4. Any pricing or availability differences
    
    Note: Don't try to log in, just observe the publicly available content.
    """

	task_id = create_task_with_proxy(task, country_code)
	return wait_for_completion(task_id)


def test_search_results_by_location(country_code: str) -> dict[str, Any]:
	"""Test how search results vary by location."""
	task = """
    Go to Google and search for "best restaurants near me" or "local news".
    
    Report:
    1. What local results appear
    2. The detected location in search results
    3. Any location-specific content or ads
    4. Language preferences
    
    This will show how search results change based on proxy location.
    """

	task_id = create_task_with_proxy(task, country_code)
	return wait_for_completion(task_id)


def wait_for_completion(task_id: str) -> dict[str, Any]:
	"""Wait for task completion and return results."""
	print(f'⏳ Waiting for task {task_id} to complete...')

	start_time = time.time()

	while True:
		response = _request_with_retry('get', f'{BASE_URL}/task/{task_id}', headers=HEADERS)
		details = response.json()

		status = details['status']
		steps = len(details.get('steps', []))
		elapsed = time.time() - start_time

		# Build status message
		if status == 'running':
			status_msg = f'🌍 Proxy task | Step {steps} | ⏱️  {elapsed:.0f}s | 🤖 Processing...'
		else:
			status_msg = f'🌍 Proxy task | Step {steps} | ⏱️  {elapsed:.0f}s | Status: {status}'

		# Clear line and show status
		print(f'\r{status_msg:<80}', end='', flush=True)

		if status == 'finished':
			print(f'\r✅ Task completed in {steps} steps! ({elapsed:.1f}s total)' + ' ' * 20)
			return details

		elif status in ['failed', 'stopped']:
			print(f'\r❌ Task {status} after {steps} steps' + ' ' * 30)
			return details

		time.sleep(3)


def demo_proxy_countries():
	"""Demonstrate proxy usage across different countries."""
	print('\n🌍 Demo 1: Proxy Countries Comparison')
	print('-' * 45)

	countries = [('us', 'United States'), ('de', 'Germany'), ('jp', 'Japan'), ('au', 'Australia')]

	results = {}

	for code, name in countries:
		print(f'\n🌍 Testing {name} ({code.upper()}) proxy:')
		print('=' * 40)

		result = test_ip_location(code)
		results[code] = result

		if result.get('output'):
			print(f'📍 Location Result: {result["output"][:200]}...')

		# Show execution URLs
		if result.get('live_url'):
			print(f'🔗 Live Preview: {result["live_url"]}')
		if result.get('public_share_url'):
			print(f'🌐 Share URL: {result["public_share_url"]}')
		elif result.get('share_url'):
			print(f'🌐 Share URL: {result["share_url"]}')

		print('-' * 40)
		time.sleep(2)  # Brief pause between tests

	# Summary comparison
	print('\n📊 Proxy Location Summary:')
	print('=' * 30)
	for code, result in results.items():
		status = result.get('status', 'unknown')
		print(f'{code.upper()}: {status}')


def demo_geo_restrictions():
	"""Demonstrate geo-restriction bypass."""
	print('\n🚫 Demo 2: Geo-Restriction Testing')
	print('-' * 40)

	# Test from different locations
	locations = [('us', 'US content'), ('de', 'European content')]

	for code, description in locations:
		print(f'\n🌍 Testing {description} with {code.upper()} proxy:')
		result = test_geo_restricted_content(code)

		if result.get('output'):
			print(f'📰 Content Access: {result["output"][:200]}...')

		time.sleep(2)


def demo_streaming_access():
	"""Demonstrate streaming service access with different proxies."""
	print('\n📺 Demo 3: Streaming Service Access')
	print('-' * 40)

	locations = [('us', 'US'), ('de', 'Germany')]

	for code, name in locations:
		print(f'\n🌍 Testing streaming access from {name}:')
		result = test_streaming_service_access(code)

		if result.get('output'):
			print(f'📺 Access Result: {result["output"][:200]}...')

		time.sleep(2)


def demo_search_localization():
	"""Demonstrate search result localization."""
	print('\n🔍 Demo 4: Search Localization')
	print('-' * 35)

	locations = [('us', 'US'), ('de', 'Germany')]

	for code, name in locations:
		print(f'\n🌍 Testing search results from {name}:')
		result = test_search_results_by_location(code)

		if result.get('output'):
			print(f'🔍 Search Results: {result["output"][:200]}...')

		time.sleep(2)


def main():
	"""Demonstrate comprehensive proxy usage."""
	print('🌍 Browser Use Cloud - Proxy Usage Examples')
	print('=' * 50)

	print('🎯 Proxy Benefits:')
	print('• Bypass geo-restrictions')
	print('• Test location-specific content')
	print('• Access region-locked websites')
	print('• Mobile/residential IP addresses')
	print('• Verify IP geolocation')

	print('\n🌐 Available Countries:')
	countries = ['🇺🇸 US', '🇫🇷 France', '🇮🇹 Italy', '🇯🇵 Japan', '🇦🇺 Australia', '🇩🇪 Germany', '🇫🇮 Finland', '🇨🇦 Canada']
	print(' • '.join(countries))

	try:
		# Parse command line arguments
		parser = argparse.ArgumentParser(description='Proxy usage examples')
		parser.add_argument(
			'--demo', choices=['countries', 'geo', 'streaming', 'search', 'all'], default='countries', help='Which demo to run'
		)
		args = parser.parse_args()

		print(f'\n🔍 Running {args.demo} demo(s)...')

		if args.demo == 'countries':
			demo_proxy_countries()
		elif args.demo == 'geo':
			demo_geo_restrictions()
		elif args.demo == 'streaming':
			demo_streaming_access()
		elif args.demo == 'search':
			demo_search_localization()
		elif args.demo == 'all':
			demo_proxy_countries()
			demo_geo_restrictions()
			demo_streaming_access()
			demo_search_localization()

	except requests.exceptions.RequestException as e:
		print(f'❌ API Error: {e}')
	except Exception as e:
		print(f'❌ Error: {e}')


if __name__ == '__main__':
	main()
