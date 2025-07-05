"""MCP Server for browser-use - exposes browser automation capabilities via Model Context Protocol.

This server provides tools for:
- Running autonomous browser tasks with an AI agent
- Direct browser control (navigation, clicking, typing, etc.)
- Content extraction from web pages
- File system operations

Usage:
    python -m browser_use.mcp_server

Or as an MCP server in Claude Desktop or other MCP clients:
    {
        "mcpServers": {
            "browser-use": {
                "command": "python",
                "args": ["-m", "browser_use.mcp_server"]
            }
        }
    }
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Add browser-use to path if running from source
sys.path.insert(0, str(Path(__file__).parent.parent))

# Override browser-use's logging BEFORE importing it
# This prevents it from setting up stdout logging
logging.basicConfig(
	level=logging.ERROR,  # Only show errors to avoid interference
	format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
	stream=sys.stderr,
	force=True,  # Force reconfiguration
)

# Clear any existing handlers on root logger
root_logger = logging.getLogger()
root_logger.handlers = []

# Add our stderr handler
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
root_logger.addHandler(stderr_handler)

from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.controller.service import Controller
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.openai.chat import ChatOpenAI

# After import, ensure browser_use logger doesn't output to stdout
browser_use_logger = logging.getLogger('browser_use')
browser_use_logger.handlers = []
browser_use_logger.addHandler(stderr_handler)
browser_use_logger.setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

# Try to import MCP SDK
try:
	import mcp.server.stdio
	import mcp.types as types
	from mcp.server import NotificationOptions, Server
	from mcp.server.models import InitializationOptions

	MCP_AVAILABLE = True
except ImportError:
	MCP_AVAILABLE = False
	logger.error('MCP SDK not installed. Install with: pip install mcp')
	sys.exit(1)


class BrowserUseServer:
	"""MCP Server for browser-use capabilities."""

	def __init__(self):
		self.server = Server('browser-use')
		self.agent: Agent | None = None
		self.browser_session: BrowserSession | None = None
		self.controller: Controller | None = None
		self.llm: ChatOpenAI | None = None
		self.file_system: FileSystem | None = None

		# Setup handlers
		self._setup_handlers()

	def _setup_handlers(self):
		"""Setup MCP server handlers."""

		@self.server.list_tools()
		async def handle_list_tools() -> list[types.Tool]:
			"""List all available browser-use tools."""
			return [
				# Agent tools
				# types.Tool(
				# 	name="browser_use_run_task",
				# 	description="Run an autonomous browser task using AI agent. The agent will navigate, interact with pages, and extract information to complete the given task.",
				# 	inputSchema={
				# 		"type": "object",
				# 		"properties": {
				# 			"task": {
				# 				"type": "string",
				# 				"description": "The task description for the AI agent to complete"
				# 			},
				# 			"max_steps": {
				# 				"type": "integer",
				# 				"description": "Maximum number of steps the agent can take",
				# 				"default": 100
				# 			},
				# 			"model": {
				# 				"type": "string",
				# 				"description": "LLM model to use (e.g., gpt-4o, claude-3-opus-20240229)",
				# 				"default": "gpt-4o"
				# 			},
				# 			"allowed_domains": {
				# 				"type": "array",
				# 				"items": {"type": "string"},
				# 				"description": "List of domains the agent is allowed to visit (security feature)",
				# 				"default": []
				# 			},
				# 			"use_vision": {
				# 				"type": "boolean",
				# 				"description": "Whether to use vision capabilities (screenshots) for the agent",
				# 				"default": True
				# 			}
				# 		},
				# 		"required": ["task"]
				# 	}
				# ),
				# Direct browser control tools
				types.Tool(
					name='browser_navigate',
					description='Navigate to a URL in the browser',
					inputSchema={
						'type': 'object',
						'properties': {
							'url': {'type': 'string', 'description': 'The URL to navigate to'},
							'new_tab': {'type': 'boolean', 'description': 'Whether to open in a new tab', 'default': False},
						},
						'required': ['url'],
					},
				),
				types.Tool(
					name='browser_click',
					description='Click an element on the page by its index',
					inputSchema={
						'type': 'object',
						'properties': {
							'index': {
								'type': 'integer',
								'description': 'The index of the element to click (from browser_get_state)',
							}
						},
						'required': ['index'],
					},
				),
				types.Tool(
					name='browser_type',
					description='Type text into an input field',
					inputSchema={
						'type': 'object',
						'properties': {
							'index': {'type': 'integer', 'description': 'The index of the input element'},
							'text': {'type': 'string', 'description': 'The text to type'},
						},
						'required': ['index', 'text'],
					},
				),
				types.Tool(
					name='browser_get_state',
					description='Get the current state of the browser including all interactive elements',
					inputSchema={
						'type': 'object',
						'properties': {
							'include_screenshot': {
								'type': 'boolean',
								'description': 'Whether to include a base64 screenshot',
								'default': False,
							}
						},
					},
				),
				types.Tool(
					name='browser_extract_content',
					description='Extract structured content from the current page based on a query',
					inputSchema={
						'type': 'object',
						'properties': {
							'query': {'type': 'string', 'description': 'What information to extract from the page'},
							'extract_links': {
								'type': 'boolean',
								'description': 'Whether to include links in the extraction',
								'default': False,
							},
						},
						'required': ['query'],
					},
				),
				types.Tool(
					name='browser_scroll',
					description='Scroll the page',
					inputSchema={
						'type': 'object',
						'properties': {
							'direction': {
								'type': 'string',
								'enum': ['up', 'down'],
								'description': 'Direction to scroll',
								'default': 'down',
							}
						},
					},
				),
				types.Tool(
					name='browser_go_back',
					description='Go back to the previous page',
					inputSchema={'type': 'object', 'properties': {}},
				),
				# types.Tool(
				# 	name="browser_close",
				# 	description="Close the browser session",
				# 	inputSchema={
				# 		"type": "object",
				# 		"properties": {}
				# 	}
				# ),
				# Tab management
				types.Tool(
					name='browser_list_tabs', description='List all open tabs', inputSchema={'type': 'object', 'properties': {}}
				),
				types.Tool(
					name='browser_switch_tab',
					description='Switch to a different tab',
					inputSchema={
						'type': 'object',
						'properties': {'tab_index': {'type': 'integer', 'description': 'Index of the tab to switch to'}},
						'required': ['tab_index'],
					},
				),
				types.Tool(
					name='browser_close_tab',
					description='Close a tab',
					inputSchema={
						'type': 'object',
						'properties': {'tab_index': {'type': 'integer', 'description': 'Index of the tab to close'}},
						'required': ['tab_index'],
					},
				),
			]

		@self.server.call_tool()
		async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
			"""Handle tool execution."""
			try:
				result = await self._execute_tool(name, arguments or {})
				return [types.TextContent(type='text', text=result)]
			except Exception as e:
				logger.error(f'Tool execution failed: {e}', exc_info=True)
				return [types.TextContent(type='text', text=f'Error: {str(e)}')]

	async def _execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
		"""Execute a browser-use tool."""

		# Agent-based tools
		if tool_name == 'browser_use_run_task':
			return await self._run_agent_task(
				task=arguments['task'],
				max_steps=arguments.get('max_steps', 100),
				model=arguments.get('model', 'gpt-4o'),
				allowed_domains=arguments.get('allowed_domains', []),
				use_vision=arguments.get('use_vision', True),
			)

		# Direct browser control tools (require active session)
		if tool_name.startswith('browser_'):
			# Ensure browser session exists
			if not self.browser_session:
				await self._init_browser_session()

			if tool_name == 'browser_navigate':
				return await self._navigate(arguments['url'], arguments.get('new_tab', False))

			elif tool_name == 'browser_click':
				return await self._click(arguments['index'])

			elif tool_name == 'browser_type':
				return await self._type_text(arguments['index'], arguments['text'])

			elif tool_name == 'browser_get_state':
				return await self._get_browser_state(arguments.get('include_screenshot', False))

			elif tool_name == 'browser_extract_content':
				return await self._extract_content(arguments['query'], arguments.get('extract_links', False))

			elif tool_name == 'browser_scroll':
				return await self._scroll(arguments.get('direction', 'down'))

			elif tool_name == 'browser_go_back':
				return await self._go_back()

			elif tool_name == 'browser_close':
				return await self._close_browser()

			elif tool_name == 'browser_list_tabs':
				return await self._list_tabs()

			elif tool_name == 'browser_switch_tab':
				return await self._switch_tab(arguments['tab_index'])

			elif tool_name == 'browser_close_tab':
				return await self._close_tab(arguments['tab_index'])

		return f'Unknown tool: {tool_name}'

	async def _init_browser_session(self, allowed_domains: list[str] = None):
		"""Initialize browser session and controller."""
		if self.browser_session:
			return

		logger.info('Initializing browser session...')

		# Create browser profile with security settings
		profile = BrowserProfile(
			allowed_domains=allowed_domains or [],
			# Enable some useful features
			downloads_path=str(Path.home() / 'Downloads' / 'browser-use-mcp'),
			wait_between_actions=0.5,
			keep_alive=True,
		)

		# Create browser session
		self.browser_session = BrowserSession(browser_profile=profile)
		await self.browser_session.start()

		# Create controller for direct actions
		self.controller = Controller()

		# Initialize LLM for extraction tasks
		api_key = os.getenv('OPENAI_API_KEY')
		if api_key:
			self.llm = ChatOpenAI(model='gpt-4o-mini', api_key=api_key)

		# Initialize FileSystem for extraction actions
		self.file_system = FileSystem(base_dir=Path.home() / '.browser-use-mcp')

		logger.info('Browser session initialized')

	async def _run_agent_task(
		self, task: str, max_steps: int = 100, model: str = 'gpt-4o', allowed_domains: list[str] = None, use_vision: bool = True
	) -> str:
		"""Run an autonomous agent task."""
		logger.info(f'Running agent task: {task}')

		# Initialize LLM
		api_key = os.getenv('OPENAI_API_KEY')
		if not api_key:
			return 'Error: OPENAI_API_KEY environment variable not set'

		llm = ChatOpenAI(model=model, api_key=api_key)

		# Create browser profile with security settings
		profile = BrowserProfile(
			allowed_domains=allowed_domains or [],
			downloads_path=str(Path.home() / 'Downloads' / 'browser-use-mcp'),
		)

		# Create and run agent
		agent = Agent(
			task=task,
			llm=llm,
			browser_profile=profile,
			use_vision=use_vision,
		)

		try:
			history = await agent.run(max_steps=max_steps)

			# Format results
			results = []
			results.append(f'Task completed in {len(history.history)} steps')
			results.append(f'Success: {history.is_successful()}')

			# Get final result if available
			final_result = history.final_result()
			if final_result:
				results.append(f'\nFinal result:\n{final_result}')

			# Include any errors
			errors = history.errors()
			if errors:
				results.append(f'\nErrors encountered:\n{json.dumps(errors, indent=2)}')

			# Include URLs visited
			urls = history.urls()
			if urls:
				results.append(f'\nURLs visited: {", ".join(urls)}')

			return '\n'.join(results)

		except Exception as e:
			logger.error(f'Agent task failed: {e}', exc_info=True)
			return f'Agent task failed: {str(e)}'
		finally:
			# Clean up
			await agent.close()

	async def _navigate(self, url: str, new_tab: bool = False) -> str:
		"""Navigate to a URL."""
		if new_tab:
			page = await self.browser_session.create_new_tab(url)
			tab_idx = self.browser_session.tabs.index(page)
			return f'Opened new tab #{tab_idx} with URL: {url}'
		else:
			await self.browser_session.navigate_to(url)
			return f'Navigated to: {url}'

	async def _click(self, index: int) -> str:
		"""Click an element by index."""
		# Get the element
		element = await self.browser_session.get_dom_element_by_index(index)
		if not element:
			return f'Element with index {index} not found'

		# Click it
		await self.browser_session._click_element_node(element)
		return f'Clicked element {index}'

	async def _type_text(self, index: int, text: str) -> str:
		"""Type text into an element."""
		element = await self.browser_session.get_dom_element_by_index(index)
		if not element:
			return f'Element with index {index} not found'

		await self.browser_session._input_text_element_node(element, text)
		return f"Typed '{text}' into element {index}"

	async def _get_browser_state(self, include_screenshot: bool = False) -> str:
		"""Get current browser state."""
		state = await self.browser_session.get_state_summary(cache_clickable_elements_hashes=False)

		result = {
			'url': state.url,
			'title': state.title,
			'tabs': [{'url': tab.url, 'title': tab.title} for tab in state.tabs],
			'interactive_elements': [],
		}

		# Add interactive elements with their indices
		for index, element in state.selector_map.items():
			elem_info = {
				'index': index,
				'tag': element.tag_name,
				'text': element.get_all_text_till_next_clickable_element(max_depth=2)[:100],
			}
			if element.attributes.get('placeholder'):
				elem_info['placeholder'] = element.attributes['placeholder']
			if element.attributes.get('href'):
				elem_info['href'] = element.attributes['href']
			result['interactive_elements'].append(elem_info)

		if include_screenshot and state.screenshot:
			result['screenshot'] = state.screenshot

		return json.dumps(result, indent=2)

	async def _extract_content(self, query: str, extract_links: bool = False) -> str:
		"""Extract content from current page."""
		if not self.llm:
			return 'Error: LLM not initialized (set OPENAI_API_KEY)'

		if not self.file_system:
			return 'Error: FileSystem not initialized'

		page = await self.browser_session.get_current_page()

		# Use the extract_structured_data action
		action_result = await self.controller.act(
			action=type(
				'Action',
				(),
				{
					'model_dump': lambda self, **kwargs: {
						'extract_structured_data': {'query': query, 'extract_links': extract_links}
					}
				},
			)(),
			browser_session=self.browser_session,
			page_extraction_llm=self.llm,
			file_system=self.file_system,
		)

		return action_result.extracted_content or 'No content extracted'

	async def _scroll(self, direction: str = 'down') -> str:
		"""Scroll the page."""
		page = await self.browser_session.get_current_page()

		# Get viewport height
		viewport_height = await page.evaluate('() => window.innerHeight')
		dy = viewport_height if direction == 'down' else -viewport_height

		await page.evaluate('(y) => window.scrollBy(0, y)', dy)
		return f'Scrolled {direction}'

	async def _go_back(self) -> str:
		"""Go back in browser history."""
		await self.browser_session.go_back()
		return 'Navigated back'

	async def _close_browser(self) -> str:
		"""Close the browser session."""
		if self.browser_session:
			await self.browser_session.stop()
			self.browser_session = None
			self.controller = None
			return 'Browser closed'
		return 'No browser session to close'

	async def _list_tabs(self) -> str:
		"""List all open tabs."""
		tabs = []
		for i, tab in enumerate(self.browser_session.tabs):
			tabs.append({'index': i, 'url': tab.url, 'title': await tab.title() if not tab.is_closed() else 'Closed'})
		return json.dumps(tabs, indent=2)

	async def _switch_tab(self, tab_index: int) -> str:
		"""Switch to a different tab."""
		await self.browser_session.switch_to_tab(tab_index)
		page = await self.browser_session.get_current_page()
		return f'Switched to tab {tab_index}: {page.url}'

	async def _close_tab(self, tab_index: int) -> str:
		"""Close a specific tab."""
		if 0 <= tab_index < len(self.browser_session.tabs):
			tab = self.browser_session.tabs[tab_index]
			url = tab.url
			await tab.close()
			return f'Closed tab {tab_index}: {url}'
		return f'Invalid tab index: {tab_index}'

	async def run(self):
		"""Run the MCP server."""
		async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
			await self.server.run(
				read_stream,
				write_stream,
				InitializationOptions(
					server_name='browser-use',
					server_version='0.1.0',
					capabilities=self.server.get_capabilities(
						notification_options=NotificationOptions(),
						experimental_capabilities={},
					),
				),
			)


async def main():
	"""Main entry point."""
	if not MCP_AVAILABLE:
		print('MCP SDK is required. Install with: pip install mcp', file=sys.stderr)
		sys.exit(1)

	server = BrowserUseServer()
	await server.run()


if __name__ == '__main__':
	asyncio.run(main())
