"""
Cloud Example 5: Search API (Beta) 🔍
=====================================

This example demonstrates the Browser Use Search API (BETA):
- Simple search: Search Google and extract from multiple results
- URL search: Extract specific content from a target URL
- Deep navigation through websites (depth parameter)
- Real-time content extraction vs cached results

Perfect for: Content extraction, research, competitive analysis
"""

import argparse
import asyncio
import json
import os
import time
from typing import Any

import aiohttp

# Configuration
API_KEY = os.getenv('BROWSER_USE_API_KEY')
if not API_KEY:
	raise ValueError('Please set BROWSER_USE_API_KEY environment variable')

BASE_URL = os.getenv('BROWSER_USE_BASE_URL', 'https://api.browser-use.com/api/v1')
TIMEOUT = int(os.getenv('BROWSER_USE_TIMEOUT', '30'))
HEADERS = {'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'}


async def simple_search(query: str, max_websites: int = 5, depth: int = 2) -> dict[str, Any]:
	"""
	Search Google and extract content from multiple top results.

	Args:
	    query: Search query to process
	    max_websites: Number of websites to process (1-10)
	    depth: How deep to navigate (2-5)

	Returns:
	    Dictionary with results from multiple websites
	"""
	# Validate input parameters
	max_websites = max(1, min(max_websites, 10))  # Clamp to 1-10
	depth = max(2, min(depth, 5))  # Clamp to 2-5

	start_time = time.time()

	print(f"🔍 Simple Search: '{query}'")
	print(f'📊 Processing {max_websites} websites at depth {depth}')
	print(f'💰 Estimated cost: {depth * max_websites}¢')

	payload = {'query': query, 'max_websites': max_websites, 'depth': depth}

	timeout = aiohttp.ClientTimeout(total=TIMEOUT)
	connector = aiohttp.TCPConnector(limit=10)  # Limit concurrent connections

	async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
		async with session.post(f'{BASE_URL}/simple-search', json=payload, headers=HEADERS) as response:
			elapsed = time.time() - start_time
			if response.status == 200:
				try:
					result = await response.json()
					print(f'✅ Found results from {len(result.get("results", []))} websites in {elapsed:.1f}s')
					return result
				except (aiohttp.ContentTypeError, json.JSONDecodeError) as e:
					error_text = await response.text()
					print(f'❌ Invalid JSON response: {e} (after {elapsed:.1f}s)')
					return {'error': 'Invalid JSON', 'details': error_text}
			else:
				error_text = await response.text()
				print(f'❌ Search failed: {response.status} - {error_text} (after {elapsed:.1f}s)')
				return {'error': f'HTTP {response.status}', 'details': error_text}


async def search_url(url: str, query: str, depth: int = 2) -> dict[str, Any]:
	"""
	Extract specific content from a target URL.

	Args:
	    url: Target URL to extract from
	    query: What specific content to look for
	    depth: How deep to navigate (2-5)

	Returns:
	    Dictionary with extracted content
	"""
	# Validate input parameters
	depth = max(2, min(depth, 5))  # Clamp to 2-5

	start_time = time.time()

	print(f'🎯 URL Search: {url}')
	print(f"🔍 Looking for: '{query}'")
	print(f'📊 Navigation depth: {depth}')
	print(f'💰 Estimated cost: {depth}¢')

	payload = {'url': url, 'query': query, 'depth': depth}

	timeout = aiohttp.ClientTimeout(total=TIMEOUT)
	connector = aiohttp.TCPConnector(limit=10)  # Limit concurrent connections

	async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
		async with session.post(f'{BASE_URL}/search-url', json=payload, headers=HEADERS) as response:
			elapsed = time.time() - start_time
			if response.status == 200:
				try:
					result = await response.json()
					print(f'✅ Extracted content from {result.get("url", "website")} in {elapsed:.1f}s')
					return result
				except (aiohttp.ContentTypeError, json.JSONDecodeError) as e:
					error_text = await response.text()
					print(f'❌ Invalid JSON response: {e} (after {elapsed:.1f}s)')
					return {'error': 'Invalid JSON', 'details': error_text}
			else:
				error_text = await response.text()
				print(f'❌ URL search failed: {response.status} - {error_text} (after {elapsed:.1f}s)')
				return {'error': f'HTTP {response.status}', 'details': error_text}


def display_simple_search_results(results: dict[str, Any]):
	"""Display simple search results in a readable format."""
	if 'error' in results:
		print(f'❌ Error: {results["error"]}')
		return

	websites = results.get('results', [])

	print(f'\n📋 Search Results ({len(websites)} websites)')
	print('=' * 50)

	for i, site in enumerate(websites, 1):
		url = site.get('url', 'Unknown URL')
		content = site.get('content', 'No content')

		print(f'\n{i}. 🌐 {url}')
		print('-' * 40)

		# Show first 300 chars of content
		if len(content) > 300:
			print(f'{content[:300]}...')
			print(f'[Content truncated - {len(content)} total characters]')
		else:
			print(content)

	# Show execution URLs if available
	if results.get('live_url'):
		print(f'\n🔗 Live Preview: {results["live_url"]}')
	if results.get('public_share_url'):
		print(f'🌐 Share URL: {results["public_share_url"]}')
	elif results.get('share_url'):
		print(f'🌐 Share URL: {results["share_url"]}')


def display_url_search_results(results: dict[str, Any]):
	"""Display URL search results in a readable format."""
	if 'error' in results:
		print(f'❌ Error: {results["error"]}')
		return

	url = results.get('url', 'Unknown URL')
	content = results.get('content', 'No content')

	print(f'\n📄 Extracted Content from: {url}')
	print('=' * 60)
	print(content)

	# Show execution URLs if available
	if results.get('live_url'):
		print(f'\n🔗 Live Preview: {results["live_url"]}')
	if results.get('public_share_url'):
		print(f'🌐 Share URL: {results["public_share_url"]}')
	elif results.get('share_url'):
		print(f'🌐 Share URL: {results["share_url"]}')


async def demo_news_search():
	"""Demo: Search for latest news across multiple sources."""
	print('\n📰 Demo 1: Latest News Search')
	print('-' * 35)

	demo_start = time.time()
	query = 'latest developments in artificial intelligence 2024'
	results = await simple_search(query, max_websites=4, depth=2)
	demo_elapsed = time.time() - demo_start

	display_simple_search_results(results)
	print(f'\n⏱️  Total demo time: {demo_elapsed:.1f}s')

	return results


async def demo_competitive_analysis():
	"""Demo: Analyze competitor websites."""
	print('\n🏢 Demo 2: Competitive Analysis')
	print('-' * 35)

	query = 'browser automation tools comparison features pricing'
	results = await simple_search(query, max_websites=3, depth=3)
	display_simple_search_results(results)

	return results


async def demo_deep_website_analysis():
	"""Demo: Deep analysis of a specific website."""
	print('\n🎯 Demo 3: Deep Website Analysis')
	print('-' * 35)

	demo_start = time.time()
	url = 'https://docs.browser-use.com'
	query = 'Browser Use features, pricing, and API capabilities'
	results = await search_url(url, query, depth=3)
	demo_elapsed = time.time() - demo_start

	display_url_search_results(results)
	print(f'\n⏱️  Total demo time: {demo_elapsed:.1f}s')

	return results


async def demo_product_research():
	"""Demo: Product research and comparison."""
	print('\n🛍️  Demo 4: Product Research')
	print('-' * 30)

	query = 'best wireless headphones 2024 reviews comparison'
	results = await simple_search(query, max_websites=5, depth=2)
	display_simple_search_results(results)

	return results


async def demo_real_time_vs_cached():
	"""Demo: Show difference between real-time and cached results."""
	print('\n⚡ Demo 5: Real-time vs Cached Data')
	print('-' * 40)

	print('🔄 Browser Use Search API benefits:')
	print('• Actually browses websites like a human')
	print('• Gets live, current data (not cached)')
	print('• Navigates deep into sites via clicks')
	print('• Handles JavaScript and dynamic content')
	print('• Accesses pages requiring navigation')

	# Example with live data
	query = 'current Bitcoin price USD live'
	results = await simple_search(query, max_websites=3, depth=2)

	print('\n💰 Live Bitcoin Price Search Results:')
	display_simple_search_results(results)

	return results


async def demo_search_depth_comparison():
	"""Demo: Compare different search depths."""
	print('\n📊 Demo 6: Search Depth Comparison')
	print('-' * 40)

	url = 'https://news.ycombinator.com'
	query = 'trending technology discussions'

	depths = [2, 3, 4]
	results = {}

	for depth in depths:
		print(f'\n🔍 Testing depth {depth}:')
		result = await search_url(url, query, depth)
		results[depth] = result

		if 'content' in result:
			content_length = len(result['content'])
			print(f'📏 Content length: {content_length} characters')

		# Brief pause between requests
		await asyncio.sleep(1)

	# Summary
	print('\n📊 Depth Comparison Summary:')
	print('-' * 30)
	for depth, result in results.items():
		if 'content' in result:
			length = len(result['content'])
			print(f'Depth {depth}: {length} characters')
		else:
			print(f'Depth {depth}: Error or no content')

	return results


async def main():
	"""Demonstrate comprehensive Search API usage."""
	print('🔍 Browser Use Cloud - Search API (BETA)')
	print('=' * 45)

	print('⚠️  Note: This API is in BETA and may change')
	print()
	print('🎯 Search API Features:')
	print('• Real-time website browsing (not cached)')
	print('• Deep navigation through multiple pages')
	print('• Dynamic content and JavaScript handling')
	print('• Multiple result aggregation')
	print('• Cost-effective content extraction')

	print('\n💰 Pricing:')
	print('• Simple Search: 1¢ × depth × websites')
	print('• URL Search: 1¢ × depth')
	print('• Example: depth=2, 5 websites = 10¢')

	try:
		# Parse command line arguments
		parser = argparse.ArgumentParser(description='Search API (BETA) examples')
		parser.add_argument(
			'--demo',
			choices=['news', 'competitive', 'deep', 'product', 'realtime', 'depth', 'all'],
			default='news',
			help='Which demo to run',
		)
		args = parser.parse_args()

		print(f'\n🔍 Running {args.demo} demo(s)...')

		if args.demo == 'news':
			await demo_news_search()
		elif args.demo == 'competitive':
			await demo_competitive_analysis()
		elif args.demo == 'deep':
			await demo_deep_website_analysis()
		elif args.demo == 'product':
			await demo_product_research()
		elif args.demo == 'realtime':
			await demo_real_time_vs_cached()
		elif args.demo == 'depth':
			await demo_search_depth_comparison()
		elif args.demo == 'all':
			await demo_news_search()
			await demo_competitive_analysis()
			await demo_deep_website_analysis()
			await demo_product_research()
			await demo_real_time_vs_cached()
			await demo_search_depth_comparison()

	except aiohttp.ClientError as e:
		print(f'❌ Network Error: {e}')
	except Exception as e:
		print(f'❌ Error: {e}')


if __name__ == '__main__':
	asyncio.run(main())
