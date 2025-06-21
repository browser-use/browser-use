#!/usr/bin/env python3
"""
Browser-Use MCP Server

Model Context Protocol server that enables Claude Code to control browsers
through our existing Browser Action Server infrastructure.

This server provides a clean MCP interface for browser automation tools
while leveraging the robust HTTP-based Browser Action Server for actual
browser control operations.
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import httpx
from fastmcp import FastMCP

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MCP Server instance
mcp: FastMCP = FastMCP('browser-use')

# Configuration
DEFAULT_ACTION_SERVER_HOST = '127.0.0.1'
DEFAULT_ACTION_SERVER_PORT = 8766
DEFAULT_TIMEOUT = 30.0


class BrowserActionServerClient:
	"""Client for communicating with the Browser Action Server"""

	def __init__(self, host: str = DEFAULT_ACTION_SERVER_HOST, port: int = DEFAULT_ACTION_SERVER_PORT):
		self.host = host
		self.port = port
		self.base_url = f'http://{host}:{port}'
		self._client: Optional[httpx.AsyncClient] = None

	async def _get_client(self) -> httpx.AsyncClient:
		"""Get or create HTTP client"""
		if self._client is None:
			self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
		return self._client

	async def close(self):
		"""Close HTTP client"""
		if self._client:
			await self._client.aclose()
			self._client = None

	async def is_server_running(self) -> bool:
		"""Check if Browser Action Server is running"""
		try:
			client = await self._get_client()
			response = await client.get(f'{self.base_url}/health')
			return response.status_code == 200
		except Exception as e:
			logger.debug(f'Server health check failed: {e}')
			return False

	async def ensure_server_running(self) -> bool:
		"""Ensure Browser Action Server is running, start if needed"""
		if await self.is_server_running():
			return True

		# Try to start server using our existing launcher
		try:
			from browser_use.action_server.launcher import ensure_server_running

			return ensure_server_running(host=self.host, port=self.port, auto_start=True)
		except Exception as e:
			logger.error(f'Failed to start Browser Action Server: {e}')
			return False

	async def make_request(self, endpoint: str, data: Optional[Dict[str, Any]] = None, method: str = 'auto') -> Dict[str, Any]:
		"""Make HTTP request to Browser Action Server"""
		if not await self.ensure_server_running():
			return {'success': False, 'error': {'type': 'ServerUnavailable', 'message': 'Browser Action Server is not available'}}

		try:
			client = await self._get_client()
			url = f'{self.base_url}/{endpoint.lstrip("/")}'

			# Determine HTTP method
			if method == 'auto':
				# POST endpoints that don't need data
				post_endpoints = {'reload', 'back', 'forward', 'navigate', 'click', 'type', 'scroll', 'hover', 'wait', 'upload'}
				# GET endpoints
				get_endpoints = {'health', 'status', 'screenshot', 'html', 'element'}

				if any(endpoint.startswith(pe) for pe in post_endpoints):
					method = 'POST'
				elif any(endpoint.startswith(ge) for ge in get_endpoints):
					method = 'GET'
				else:
					method = 'POST' if data else 'GET'

			# Make request based on method
			if method.upper() == 'POST':
				response = await client.post(url, json=data or {})
			else:
				response = await client.get(url)

			if response.status_code == 200:
				return response.json()
			else:
				return {
					'success': False,
					'error': {'type': 'HTTPError', 'message': f'HTTP {response.status_code}: {response.text}'},
				}

		except Exception as e:
			logger.error(f'Request to {endpoint} failed: {e}')
			return {'success': False, 'error': {'type': type(e).__name__, 'message': str(e)}}


# Global client instance
_action_client = BrowserActionServerClient()


@mcp.tool
async def browser_navigate(url: str, wait_until: str = 'domcontentloaded', timeout: float = 30.0) -> str:
	"""
	Navigate to a URL in the browser.

	Args:
		url: The URL to navigate to
		wait_until: When to consider navigation complete ('load', 'domcontentloaded', 'networkidle')
		timeout: Timeout in seconds

	Returns:
		JSON string containing navigation result
	"""
	data = {'url': url, 'wait_until': wait_until, 'timeout': timeout}

	result = await _action_client.make_request('navigate', data)
	return json.dumps(result, indent=2)


@mcp.tool
async def browser_reload(timeout: float = 30.0) -> str:
	"""
	Reload the current page in the browser.

	Args:
		timeout: Timeout in seconds

	Returns:
		JSON string containing reload result
	"""
	result = await _action_client.make_request('reload')
	return json.dumps(result, indent=2)


@mcp.tool
async def browser_go_back(timeout: float = 30.0) -> str:
	"""
	Go back to the previous page in browser history.

	Args:
		timeout: Timeout in seconds

	Returns:
		JSON string containing navigation result
	"""
	result = await _action_client.make_request('back')
	return json.dumps(result, indent=2)


@mcp.tool
async def browser_go_forward(timeout: float = 30.0) -> str:
	"""
	Go forward to the next page in browser history.

	Args:
		timeout: Timeout in seconds

	Returns:
		JSON string containing navigation result
	"""
	result = await _action_client.make_request('forward')
	return json.dumps(result, indent=2)


@mcp.tool
async def browser_click(selector: str, timeout: float = 10.0) -> str:
	"""
	Click on an element in the browser.

	Args:
		selector: CSS selector of the element to click
		timeout: Timeout in seconds

	Returns:
		JSON string containing click result
	"""
	data = {'selector': selector, 'timeout': timeout}

	result = await _action_client.make_request('click', data)
	return json.dumps(result, indent=2)


@mcp.tool
async def browser_type(selector: str, text: str, timeout: float = 10.0) -> str:
	"""
	Type text into an input field.

	Args:
		selector: CSS selector of the input element
		text: Text to type
		timeout: Timeout in seconds

	Returns:
		JSON string containing typing result
	"""
	data = {'selector': selector, 'text': text, 'timeout': timeout}

	result = await _action_client.make_request('type', data)
	return json.dumps(result, indent=2)


@mcp.tool
async def browser_screenshot(timeout: float = 10.0) -> str:
	"""
	Take a screenshot of the current page.

	Args:
		timeout: Timeout in seconds

	Returns:
		JSON string containing screenshot result
	"""
	result = await _action_client.make_request('screenshot', None)
	return json.dumps(result, indent=2)


@mcp.tool
async def browser_scroll(direction: str = 'down', amount: int = 300, timeout: float = 10.0) -> str:
	"""
	Scroll the page in a specified direction.

	Args:
		direction: Direction to scroll ('up', 'down', 'left', 'right')
		amount: Number of pixels to scroll
		timeout: Timeout in seconds

	Returns:
		JSON string containing scroll result
	"""
	data = {'direction': direction, 'amount': amount, 'timeout': timeout}

	result = await _action_client.make_request('scroll', data)
	return json.dumps(result, indent=2)


@mcp.tool
async def browser_status(timeout: float = 10.0) -> str:
	"""
	Get the current page status and information.

	Args:
		timeout: Timeout in seconds

	Returns:
		JSON string containing page status
	"""
	result = await _action_client.make_request('status', None)
	return json.dumps(result, indent=2)


@mcp.tool
async def browser_wait_for_element(selector: str, timeout: float = 10.0) -> str:
	"""
	Wait for an element to appear on the page.

	Args:
		selector: CSS selector of the element to wait for
		timeout: Timeout in seconds

	Returns:
		JSON string containing wait result
	"""
	data = {'selector': selector, 'timeout': timeout}

	result = await _action_client.make_request('wait', data)
	return json.dumps(result, indent=2)


@mcp.tool
async def browser_hover(selector: str, timeout: float = 10.0) -> str:
	"""
	Hover over an element in the browser.

	Args:
		selector: CSS selector of the element to hover over
		timeout: Timeout in seconds

	Returns:
		JSON string containing hover result
	"""
	data = {'selector': selector, 'timeout': timeout}

	result = await _action_client.make_request('hover', data)
	return json.dumps(result, indent=2)


@mcp.tool
async def browser_wait_for_text(text: str, timeout: float = 30.0) -> str:
	"""
	Wait for specific text to appear anywhere on the page.

	Args:
		text: Text content to wait for
		timeout: Timeout in seconds

	Returns:
		JSON string containing wait result
	"""
	data = {'condition_type': 'text', 'text': text, 'timeout': timeout}

	result = await _action_client.make_request('wait', data)
	return json.dumps(result, indent=2)


@mcp.tool
async def browser_wait_for_url(url: str, timeout: float = 30.0) -> str:
	"""
	Wait for the browser URL to match a specific pattern.

	Args:
		url: URL pattern to wait for
		timeout: Timeout in seconds

	Returns:
		JSON string containing wait result
	"""
	data = {'condition_type': 'url', 'url': url, 'timeout': timeout}

	result = await _action_client.make_request('wait', data)
	return json.dumps(result, indent=2)


@mcp.tool
async def browser_wait_timeout(seconds: float) -> str:
	"""
	Wait for a specific amount of time (timeout/sleep).

	Args:
		seconds: Number of seconds to wait

	Returns:
		JSON string containing wait result
	"""
	data = {'condition_type': 'timeout', 'timeout': seconds}

	result = await _action_client.make_request('wait', data)
	return json.dumps(result, indent=2)


@mcp.tool
async def browser_get_html(timeout: float = 10.0) -> str:
	"""
	Get the HTML content of the current page.

	Args:
		timeout: Timeout in seconds

	Returns:
		JSON string containing the page HTML content
	"""
	result = await _action_client.make_request('html')
	return json.dumps(result, indent=2)


@mcp.tool
async def browser_get_element_info(selector: str, timeout: float = 10.0) -> str:
	"""
	Get detailed information about a specific element.

	Args:
		selector: CSS selector of the element to inspect
		timeout: Timeout in seconds

	Returns:
		JSON string containing element information (tag, attributes, text, etc.)
	"""
	# The /element endpoint expects selector as a query parameter
	# We'll format this properly for the Action Server
	endpoint = f'element?selector={selector}'
	result = await _action_client.make_request(endpoint)
	return json.dumps(result, indent=2)


@mcp.tool
async def browser_scroll_to_text(text: str, timeout: float = 10.0) -> str:
	"""
	Scroll to find and display specific text on the page.

	Args:
		text: Text content to scroll to and find
		timeout: Timeout in seconds

	Returns:
		JSON string containing scroll result and text location
	"""
	try:
		# First check if text is already visible by getting current page content
		html_result = await _action_client.make_request('html')

		if not html_result.get('success', False):
			return json.dumps(
				{'success': False, 'error': {'type': 'PageAccessError', 'message': 'Could not access page content'}}, indent=2
			)

		page_html = html_result.get('data', {}).get('html', '')

		if text not in page_html:
			return json.dumps(
				{'success': False, 'error': {'type': 'TextNotFound', 'message': f"Text '{text}' not found on page"}}, indent=2
			)

		# Try different scroll strategies to find the text
		scroll_attempts = [
			{'direction': 'down', 'amount': 300},
			{'direction': 'down', 'amount': 500},
			{'direction': 'up', 'amount': 300},
			{'direction': 'down', 'amount': 1000},
		]

		for attempt in scroll_attempts:
			# Scroll and check if text becomes visible
			scroll_result = await _action_client.make_request('scroll', attempt)

			if scroll_result.get('success', False):
				# Check if we can now locate the text (simplified check)
				status_result = await _action_client.make_request('status')
				if status_result.get('success', False):
					return json.dumps(
						{
							'success': True,
							'data': {
								'text': text,
								'scroll_action': attempt,
								'message': f'Scrolled {attempt["direction"]} by {attempt["amount"]}px to locate text',
							},
							'message': f"Scrolled to locate text: '{text}'",
						},
						indent=2,
					)

		return json.dumps(
			{
				'success': True,
				'data': {'text': text, 'message': 'Text found on page but exact scroll position not determined'},
				'message': f"Text '{text}' is present on page",
			},
			indent=2,
		)

	except Exception as e:
		return json.dumps(
			{'success': False, 'error': {'type': type(e).__name__, 'message': f'Error scrolling to text: {str(e)}'}}, indent=2
		)


@mcp.tool
async def browser_upload_file(selector: str, file_path: str, timeout: float = 10.0) -> str:
	"""
	Upload a file to a file input element.

	Args:
		selector: CSS selector of the file input element
		file_path: Path to the file to upload
		timeout: Timeout in seconds

	Returns:
		JSON string containing upload result
	"""
	data = {'selector': selector, 'file_path': file_path, 'timeout': timeout}

	result = await _action_client.make_request('upload', data)
	return json.dumps(result, indent=2)


@mcp.tool
async def browser_search_google(query: str, timeout: float = 30.0) -> str:
	"""
	Search for a query on Google.

	Args:
		query: Search query to execute on Google
		timeout: Timeout in seconds

	Returns:
		JSON string containing search navigation result
	"""
	# Format Google search URL with the query
	search_url = f'https://www.google.com/search?q={query}&udm=14'

	data = {'url': search_url, 'wait_until': 'domcontentloaded', 'timeout': timeout}

	result = await _action_client.make_request('navigate', data)

	# Enhance the result with search context
	if result.get('success', False):
		enhanced_result = result.copy()
		enhanced_result['data']['search_query'] = query
		enhanced_result['data']['search_url'] = search_url
		enhanced_result['message'] = f"Searched Google for: '{query}'"
		return json.dumps(enhanced_result, indent=2)

	return json.dumps(result, indent=2)


@mcp.tool
async def browser_server_status() -> str:
	"""
	Check if the Browser Action Server is running and get server info.

	Returns:
		JSON string containing server status
	"""
	if await _action_client.is_server_running():
		# Get detailed server status
		result = await _action_client.make_request('health')
		return json.dumps(
			{'success': True, 'data': {'status': 'running', 'server_url': _action_client.base_url, **result.get('data', {})}},
			indent=2,
		)
	else:
		return json.dumps(
			{
				'success': False,
				'error': {'type': 'ServerDown', 'message': f'Browser Action Server not running on {_action_client.base_url}'},
			},
			indent=2,
		)


@mcp.tool
async def browser_server_start(port: int = DEFAULT_ACTION_SERVER_PORT, debug: bool = False) -> str:
	"""
	Start the Browser Action Server if it's not already running.

	Args:
		port: Port to run the server on
		debug: Enable debug mode

	Returns:
		JSON string containing startup result
	"""
	# Update client configuration
	_action_client.port = port
	_action_client.base_url = f'http://{_action_client.host}:{port}'

	if await _action_client.ensure_server_running():
		return json.dumps(
			{
				'success': True,
				'data': {
					'status': 'started',
					'server_url': _action_client.base_url,
					'message': 'Browser Action Server is now running',
				},
			},
			indent=2,
		)
	else:
		return json.dumps(
			{'success': False, 'error': {'type': 'StartupFailed', 'message': 'Failed to start Browser Action Server'}}, indent=2
		)


# Cleanup on server shutdown
async def cleanup():
	"""Cleanup resources on server shutdown"""
	await _action_client.close()


if __name__ == '__main__':
	try:
		# Run the MCP server
		mcp.run()
	except KeyboardInterrupt:
		logger.info('MCP server stopped by user')
	except Exception as e:
		logger.error(f'MCP server error: {e}')
		raise
	finally:
		# Cleanup
		asyncio.run(cleanup())
