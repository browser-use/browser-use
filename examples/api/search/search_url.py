"""
Search URL API Example

This example shows how to use the Browser Use API to extract specific
content from a given URL based on your query.

Usage:
    # Copy this function and customize the parameters
    result = await search_url("https://example.com", "what to find", depth=2)
"""

import asyncio
import os

import aiohttp
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


async def search_url(url: str, query: str, depth: int = 2):
	# Validate API key exists
	api_key = os.getenv('BROWSER_USE_API_KEY')
	if not api_key:
		print('❌ Error: BROWSER_USE_API_KEY environment variable is not set.')
		print('Please set your API key: export BROWSER_USE_API_KEY="your_api_key_here"')
		return None

	payload = {'url': url, 'query': query, 'depth': depth}

	headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}

	print('Testing Search URL API...')
	print(f'URL: {url}')
	print(f'Query: {query}')
	print(f'Depth: {depth}')
	print('-' * 50)

	try:
		async with aiohttp.ClientSession() as session:
			async with session.post(
				'https://api.browser-use.com/api/v1/search-url',
				json=payload,
				headers=headers,
				timeout=aiohttp.ClientTimeout(total=300),
			) as response:
				if response.status == 200:
					result = await response.json()
					print('✅ Success!')
					print(f'URL processed: {result.get("url", "N/A")}')
					content = result.get('content', '')
					print(f'Content: {content}')
					return result
				else:
					error_text = await response.text()
					print(f'❌ Error {response.status}: {error_text}')
					return None
	except Exception as e:
		print(f'❌ Exception: {str(e)}')
		return None


if __name__ == '__main__':
	# Example 1: Extract pricing info
	asyncio.run(search_url('https://browser-use.com/#pricing', 'Find pricing information for Browser Use'))

	# Example 2: News article analysis
	# asyncio.run(search_url("https://techcrunch.com", "latest startup funding news", depth=3))

	# Example 3: Product research
	# asyncio.run(search_url("https://github.com/browser-use/browser-use", "installation instructions", depth=2))
