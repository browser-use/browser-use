"""
Simple Search API Example

This example shows how to use the Browser Use API to search and extract
content from multiple websites based on a query.

Usage:
    # Copy this function and customize the parameters
    result = await simple_search("your search query", max_websites=5, depth=2)
"""

import asyncio
import os

import aiohttp
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


async def simple_search(query: str, max_websites: int = 5, depth: int = 2):
	# Validate API key exists
	api_key = os.getenv('BROWSER_USE_API_KEY')
	if not api_key:
		print('❌ Error: BROWSER_USE_API_KEY environment variable is not set.')
		print('Please set your API key: export BROWSER_USE_API_KEY="your_api_key_here"')
		return None

	payload = {'query': query, 'max_websites': max_websites, 'depth': depth}

	headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}

	print('Testing Simple Search API...')
	print(f'Query: {query}')
	print(f'Max websites: {max_websites}')
	print(f'Depth: {depth}')
	print('-' * 50)

	try:
		async with aiohttp.ClientSession() as session:
			async with session.post(
				'https://api.browser-use.com/api/v1/simple-search',
				json=payload,
				headers=headers,
				timeout=aiohttp.ClientTimeout(total=300),
			) as response:
				if response.status == 200:
					result = await response.json()
					print('✅ Success!')
					print(f'Results: {len(result.get("results", []))} websites processed')
					for i, item in enumerate(result.get('results', [])[:2], 1):
						print(f'\n{i}. {item.get("url", "N/A")}')
						content = item.get('content', '')
						print(f'   Content: {content}')
					return result
				else:
					error_text = await response.text()
					print(f'❌ Error {response.status}: {error_text}')
					return None
	except Exception as e:
		print(f'❌ Exception: {str(e)}')
		return None


if __name__ == '__main__':
	# Example 1: Basic search
	asyncio.run(simple_search('latest AI news'))

	# Example 2: Custom parameters
	# asyncio.run(simple_search("python web scraping", max_websites=3, depth=3))

	# Example 3: Research query
	# asyncio.run(simple_search("climate change solutions 2024", max_websites=7, depth=2))
