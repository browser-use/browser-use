"""
Simple example of connecting to browser-use MCP server as a client.

This example demonstrates how to use the MCP client library to connect to
a running browser-use MCP server and call its browser automation tools.

Prerequisites:
1. Install required packages:
   pip install 'browser-use[cli]'

2. Start the browser-use MCP server in a separate terminal:
   uvx browser-use --mcp

3. Run this client example:
   python simple_server.py

This shows the actual MCP protocol flow between a client and the browser-use server.
"""

import asyncio
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent


async def run_simple_browser_automation():
	"""Connect to browser-use MCP server and perform basic browser automation."""

	# Create connection parameters for the browser-use MCP server
	server_params = StdioServerParameters(command='uvx', args=['browser-use', '--mcp'], env={})

	async with stdio_client(server_params) as (read, write):
		async with ClientSession(read, write) as session:
			# Initialize the connection
			await session.initialize()

			print('✅ Connected to browser-use MCP server')

			# List available tools
			tools_result = await session.list_tools()
			tools = tools_result.tools
			print(f'\n📋 Available tools: {len(tools)}')
			for tool in tools:
				print(f'  - {tool.name}: {tool.description}')

			# Example 1: Navigate to a website
			print('\n🌐 Navigating to example.com...')
			result = await session.call_tool('browser_navigate', arguments={'url': 'https://example.com'})
			# Handle different content types
			content = result.content[0]
			if isinstance(content, TextContent):
				print(f'Result: {content.text}')
			else:
				print(f'Result: {content}')

			# Example 2: Get the current browser state
			print('\n🔍 Getting browser state...')
			result = await session.call_tool('browser_get_state', arguments={'include_screenshot': False})
			# Handle different content types
			content = result.content[0]
			if isinstance(content, TextContent):
				state = json.loads(content.text)
			else:
				state = json.loads(str(content))
			print(f'Page title: {state["title"]}')
			print(f'URL: {state["url"]}')
			print(f'Interactive elements found: {len(state["interactive_elements"])}')

			# Example 3: Open a new tab
			print('\n📑 Opening Python.org in a new tab...')
			result = await session.call_tool('browser_navigate', arguments={'url': 'https://python.org', 'new_tab': True})
			# Handle different content types
			content = result.content[0]
			if isinstance(content, TextContent):
				print(f'Result: {content.text}')
			else:
				print(f'Result: {content}')

			# Example 4: List all open tabs
			print('\n📋 Listing all tabs...')
			result = await session.call_tool('browser_list_tabs', arguments={})
			# Handle different content types
			content = result.content[0]
			if isinstance(content, TextContent):
				tabs = json.loads(content.text)
			else:
				tabs = json.loads(str(content))
			for tab in tabs:
				print(f'  Tab {tab["index"]}: {tab["title"]} - {tab["url"]}')

			# Example 5: Click on an element
			print('\n👆 Looking for clickable elements...')
			state_result = await session.call_tool('browser_get_state', arguments={'include_screenshot': False})
			# Handle different content types
			content = state_result.content[0]
			if isinstance(content, TextContent):
				state = json.loads(content.text)
			else:
				state = json.loads(str(content))

			# Find a link to click
			link_element = None
			for elem in state['interactive_elements']:
				if elem['tag'] == 'a' and elem.get('href'):
					link_element = elem
					break

			if link_element:
				print(f'Clicking on link: {link_element.get("text", "unnamed")[:50]}...')
				result = await session.call_tool('browser_click', arguments={'index': link_element['index']})
				# Handle different content types
				content = result.content[0]
				if isinstance(content, TextContent):
					print(f'Result: {content.text}')
				else:
					print(f'Result: {content}')

			print('\n✨ Simple browser automation demo complete!')


async def main():
	"""Main entry point."""
	print('Browser-Use MCP Client - Simple Example')
	print('=' * 50)
	print('\nConnecting to browser-use MCP server...\n')

	try:
		await run_simple_browser_automation()
	except Exception as e:
		print(f'\n❌ Error: {e}')
		print('\nMake sure the browser-use MCP server is running:')
		print('  uvx browser-use --mcp')


if __name__ == '__main__':
	asyncio.run(main())
