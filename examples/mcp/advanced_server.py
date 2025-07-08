"""
Advanced example of building an AI assistant that uses browser-use MCP server.

This example shows how to build a more sophisticated MCP client that:
- Connects to multiple MCP servers (browser-use + filesystem)
- Orchestrates complex multi-step workflows
- Handles errors and retries
- Provides a conversational interface

Prerequisites:
1. Install required packages:
   pip install 'browser-use[cli]'

2. Start the browser-use MCP server:
   uvx browser-use --mcp

3. Run this example:
   python advanced_server.py

This demonstrates real-world usage patterns for the MCP protocol.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent, Tool


@dataclass
class TaskResult:
	"""Result of executing a task."""

	success: bool
	data: Any
	error: str | None = None
	timestamp: datetime | None = None

	def __post_init__(self):
		if self.timestamp is None:
			self.timestamp = datetime.now()


class AIAssistant:
	"""An AI assistant that uses MCP servers to perform complex tasks."""

	def __init__(self):
		self.servers: dict[str, ClientSession] = {}
		self.tools: dict[str, Tool] = {}
		self.history: list[TaskResult] = []

	async def connect_server(self, name: str, command: str, args: list[str], env: dict[str, str] | None = None):
		"""Connect to an MCP server and discover its tools."""
		print(f'\n🔌 Connecting to {name} server...')

		server_params = StdioServerParameters(command=command, args=args, env=env or {})

		try:
			# Create connection
			read, write = await stdio_client(server_params).__aenter__()
			session = ClientSession(read, write)
			await session.__aenter__()
			await session.initialize()

			# Store session
			self.servers[name] = session

			# Discover tools
			tools_result = await session.list_tools()
			tools = tools_result.tools
			for tool in tools:
				# Prefix tool names with server name to avoid conflicts
				prefixed_name = f'{name}.{tool.name}'
				self.tools[prefixed_name] = tool
				print(f'  ✓ Discovered: {prefixed_name}')

			print(f'✅ Connected to {name} with {len(tools)} tools')

		except Exception as e:
			print(f'❌ Failed to connect to {name}: {e}')
			raise

	async def disconnect_all(self):
		"""Disconnect from all MCP servers."""
		for name, session in self.servers.items():
			try:
				await session.__aexit__(None, None, None)
				print(f'📴 Disconnected from {name}')
			except Exception as e:
				print(f'⚠️ Error disconnecting from {name}: {e}')

	async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> TaskResult:
		"""Call a tool on the appropriate MCP server."""
		# Parse server and tool name
		if '.' not in tool_name:
			return TaskResult(False, None, "Invalid tool name format. Use 'server.tool'")

		server_name, actual_tool_name = tool_name.split('.', 1)

		# Check if server is connected
		if server_name not in self.servers:
			return TaskResult(False, None, f"Server '{server_name}' not connected")

		# Call the tool
		try:
			session = self.servers[server_name]
			result = await session.call_tool(actual_tool_name, arguments)

			# Extract text content
			text_content = [c.text for c in result.content if isinstance(c, TextContent)]
			data = text_content[0] if text_content else str(result.content)

			task_result = TaskResult(True, data)
			self.history.append(task_result)
			return task_result

		except Exception as e:
			error_result = TaskResult(False, None, str(e))
			self.history.append(error_result)
			return error_result

	async def search_and_save(self, query: str, output_file: str) -> TaskResult:
		"""Search for information and save results to a file."""
		print(f'\n🔍 Searching for: {query}')

		# Step 1: Navigate to search engine
		print('  1️⃣ Opening DuckDuckGo...')
		nav_result = await self.call_tool('browser.browser_navigate', {'url': f'https://duckduckgo.com/?q={query}'})
		if not nav_result.success:
			return nav_result

		await asyncio.sleep(2)  # Wait for page load

		# Step 2: Get search results
		print('  2️⃣ Extracting search results...')
		extract_result = await self.call_tool(
			'browser.browser_extract_content',
			{'query': 'Extract the top 5 search results with titles and descriptions', 'extract_links': True},
		)
		if not extract_result.success:
			return extract_result

		# Step 3: Save to file (if filesystem server is connected)
		if 'filesystem' in self.servers:
			print(f'  3️⃣ Saving results to {output_file}...')
			save_result = await self.call_tool(
				'filesystem.write_file',
				{'path': output_file, 'content': f'Search Query: {query}\n\nResults:\n{extract_result.data}'},
			)
			if save_result.success:
				print(f'  ✅ Results saved to {output_file}')
		else:
			print('  ⚠️ Filesystem server not connected, skipping save')

		return extract_result

	async def monitor_page_changes(self, url: str, duration: int = 10, interval: int = 2):
		"""Monitor a webpage for changes over time."""
		print(f'\n📊 Monitoring {url} for {duration} seconds...')

		# Navigate to page
		await self.call_tool('browser.browser_navigate', {'url': url})
		await asyncio.sleep(2)

		changes = []
		start_time = datetime.now()

		while (datetime.now() - start_time).seconds < duration:
			# Get current state
			state_result = await self.call_tool('browser.browser_get_state', {'include_screenshot': False})

			if state_result.success:
				state = json.loads(state_result.data)
				changes.append(
					{
						'timestamp': datetime.now().isoformat(),
						'title': state.get('title', ''),
						'element_count': len(state.get('interactive_elements', [])),
					}
				)
				print(f'  📸 Captured state at {changes[-1]["timestamp"]}')

			await asyncio.sleep(interval)

		return TaskResult(True, changes)

	async def fill_form_workflow(self, form_url: str, form_data: dict[str, str]):
		"""Navigate to a form and fill it out."""
		print(f'\n📝 Form filling workflow for {form_url}')

		# Step 1: Navigate to form
		print('  1️⃣ Navigating to form...')
		nav_result = await self.call_tool('browser.browser_navigate', {'url': form_url})
		if not nav_result.success:
			return nav_result

		await asyncio.sleep(2)

		# Step 2: Get form elements
		print('  2️⃣ Analyzing form elements...')
		state_result = await self.call_tool('browser.browser_get_state', {'include_screenshot': False})

		if not state_result.success:
			return state_result

		state = json.loads(state_result.data)

		# Step 3: Fill form fields
		print('  3️⃣ Filling form fields...')
		filled_fields = []

		for element in state.get('interactive_elements', []):
			# Look for input fields
			if element.get('tag') in ['input', 'textarea']:
				# Try to match field by placeholder or nearby text
				for field_name, field_value in form_data.items():
					element_text = str(element).lower()
					if field_name.lower() in element_text:
						print(f'    ✏️ Filling {field_name}...')
						type_result = await self.call_tool(
							'browser.browser_type', {'index': element['index'], 'text': field_value}
						)
						if type_result.success:
							filled_fields.append(field_name)
						await asyncio.sleep(0.5)
						break

		return TaskResult(True, {'filled_fields': filled_fields, 'form_data': form_data, 'url': form_url})


async def main():
	"""Main demonstration of advanced MCP client usage."""
	print('Browser-Use MCP Client - Advanced Example')
	print('=' * 50)

	assistant = AIAssistant()

	try:
		# Connect to browser-use MCP server
		await assistant.connect_server(name='browser', command='uvx', args=['browser-use', '--mcp'])

		# Optionally connect to filesystem server
		# Note: Uncomment to enable file operations
		# await assistant.connect_server(
		#     name="filesystem",
		#     command="npx",
		#     args=["@modelcontextprotocol/server-filesystem", "."]
		# )

		print('\n' + '=' * 50)
		print('Starting demonstration workflows...')
		print('=' * 50)

		# Demo 1: Search and extract
		print('\n📌 Demo 1: Web Search and Extraction')
		search_result = await assistant.search_and_save(query='MCP protocol browser automation', output_file='search_results.txt')
		print(f'Search completed: {"✅" if search_result.success else "❌"}')

		# Demo 2: Multi-tab comparison
		print('\n📌 Demo 2: Multi-tab News Comparison')
		news_sites = [('BBC News', 'https://bbc.com/news'), ('CNN', 'https://cnn.com'), ('Reuters', 'https://reuters.com')]

		for i, (name, url) in enumerate(news_sites):
			print(f'\n  📰 Opening {name}...')
			await assistant.call_tool('browser.browser_navigate', {'url': url, 'new_tab': i > 0})
			await asyncio.sleep(2)

		# List all tabs
		tabs_result = await assistant.call_tool('browser.browser_list_tabs', {})
		if tabs_result.success:
			tabs = json.loads(tabs_result.data)
			print(f'\n  📑 Opened {len(tabs)} news sites:')
			for tab in tabs:
				print(f'    - Tab {tab["index"]}: {tab["title"]}')

		# Demo 3: Form filling
		print('\n📌 Demo 3: Automated Form Filling')
		form_result = await assistant.fill_form_workflow(
			form_url='https://httpbin.org/forms/post',
			form_data={
				'custname': 'AI Assistant',
				'custtel': '555-0123',
				'custemail': 'ai@example.com',
				'comments': 'Testing MCP browser automation',
			},
		)
		if form_result.success:
			print(f'  ✅ Filled {len(form_result.data["filled_fields"])} fields')

		# Demo 4: Page monitoring
		print('\n📌 Demo 4: Dynamic Page Monitoring')
		monitor_result = await assistant.monitor_page_changes(url='https://time.is/', duration=10, interval=3)
		if monitor_result.success:
			print(f'  📊 Collected {len(monitor_result.data)} snapshots')

		# Summary
		print('\n' + '=' * 50)
		print('📊 Session Summary')
		print('=' * 50)

		success_count = sum(1 for r in assistant.history if r.success)
		total_count = len(assistant.history)

		print(f'Total operations: {total_count}')
		print(f'Successful: {success_count}')
		print(f'Failed: {total_count - success_count}')
		print(f'Success rate: {success_count / total_count * 100:.1f}%')

	except Exception as e:
		print(f'\n❌ Fatal error: {e}')

	finally:
		# Always disconnect
		print('\n🧹 Cleaning up...')
		await assistant.disconnect_all()
		print('✨ Demo complete!')


if __name__ == '__main__':
	asyncio.run(main())
