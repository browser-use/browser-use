"""MCP Server for browser-use - exposes browser automation capabilities via Model Context Protocol.

This server provides tools for:
- Running autonomous browser tasks with an AI agent
- Direct browser control (navigation, clicking, typing, etc.)
- Content extraction from web pages
- File system operations

Usage:
    uvx browser-use --mcp

Or as an MCP server in Claude Desktop or other MCP clients:
    {
        "mcpServers": {
            "browser-use": {
                "command": "uvx",
                "args": ["browser-use[cli]", "--mcp"],
                "env": {
                    "OPENAI_API_KEY": "sk-proj-1234567890",
                }
            }
        }
    }
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
	import psutil

	PSUTIL_AVAILABLE = True
except ImportError:
	PSUTIL_AVAILABLE = False

# Add browser-use to path if running from source
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import and configure logging to use stderr before other imports
from browser_use.logging_config import setup_logging


def _configure_mcp_server_logging():
	"""Configure logging for MCP server mode - redirect all logs to stderr to prevent JSON RPC interference."""
	# Set environment to suppress browser-use logging during server mode
	os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'error'
	os.environ['BROWSER_USE_SETUP_LOGGING'] = 'false'  # Prevent automatic logging setup

	# Configure logging to stderr for MCP mode
	setup_logging(stream=sys.stderr, log_level='error', force_setup=True)

	# Also configure the root logger and all existing loggers to use stderr
	logging.root.handlers = []
	stderr_handler = logging.StreamHandler(sys.stderr)
	stderr_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
	logging.root.addHandler(stderr_handler)
	logging.root.setLevel(logging.ERROR)

	# Configure all existing loggers to use stderr
	for name in list(logging.root.manager.loggerDict.keys()):
		logger_obj = logging.getLogger(name)
		logger_obj.handlers = []
		logger_obj.addHandler(stderr_handler)
		logger_obj.setLevel(logging.ERROR)
		logger_obj.propagate = False


# Configure MCP server logging before any browser_use imports to capture early log lines
_configure_mcp_server_logging()

# Import browser_use modules
from browser_use import ActionModel, Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.config import get_default_llm, get_default_profile, load_browser_use_config
from browser_use.controller.service import Controller
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.openai.chat import ChatOpenAI

logger = logging.getLogger(__name__)


def _ensure_all_loggers_use_stderr():
	"""Ensure ALL loggers only output to stderr, not stdout."""
	# Get the stderr handler
	stderr_handler = None
	for handler in logging.root.handlers:
		if hasattr(handler, 'stream') and handler.stream == sys.stderr:  # type: ignore
			stderr_handler = handler
			break

	if not stderr_handler:
		stderr_handler = logging.StreamHandler(sys.stderr)
		stderr_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

	# Configure root logger
	logging.root.handlers = [stderr_handler]
	logging.root.setLevel(logging.ERROR)

	# Configure all existing loggers
	for name in list(logging.root.manager.loggerDict.keys()):
		logger_obj = logging.getLogger(name)
		logger_obj.handlers = [stderr_handler]
		logger_obj.setLevel(logging.ERROR)
		logger_obj.propagate = False


# Ensure stderr logging after all imports
_ensure_all_loggers_use_stderr()


# Try to import MCP SDK
try:
	import contextlib

	import mcp.server.stdio
	import mcp.types as types
	from mcp.server import NotificationOptions, Server
	from mcp.server.models import InitializationOptions
	from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
	from starlette.applications import Starlette
	from starlette.routing import Mount
	from starlette.types import Receive, Scope, Send

	MCP_AVAILABLE = True

	# Configure MCP SDK logging to stderr as well
	mcp_logger = logging.getLogger('mcp')
	mcp_logger.handlers = []
	mcp_logger.addHandler(logging.root.handlers[0] if logging.root.handlers else logging.StreamHandler(sys.stderr))
	mcp_logger.setLevel(logging.ERROR)
	mcp_logger.propagate = False
except ImportError:
	MCP_AVAILABLE = False
	logger.error('MCP SDK not installed. Install with: pip install mcp')
	sys.exit(1)

from browser_use.telemetry import MCPServerTelemetryEvent, ProductTelemetry
from browser_use.utils import get_browser_use_version


def get_parent_process_cmdline() -> str | None:
	"""Get the command line of all parent processes up the chain."""
	if not PSUTIL_AVAILABLE:
		return None

	try:
		cmdlines = []
		current_process = psutil.Process()
		parent = current_process.parent()

		while parent:
			try:
				cmdline = parent.cmdline()
				if cmdline:
					cmdlines.append(' '.join(cmdline))
			except (psutil.AccessDenied, psutil.NoSuchProcess):
				# Skip processes we can't access (like system processes)
				pass

			try:
				parent = parent.parent()
			except (psutil.AccessDenied, psutil.NoSuchProcess):
				# Can't go further up the chain
				break

		return ';'.join(cmdlines) if cmdlines else None
	except Exception:
		# If we can't get parent process info, just return None
		return None


class BrowserUseServer:
	"""MCP Server for browser-use capabilities."""

	def __init__(self):
		# Ensure all logging goes to stderr (in case new loggers were created)
		_ensure_all_loggers_use_stderr()

		self.server = Server('browser-use')
		self.config = load_browser_use_config()
		self.agent: Agent | None = None
		self.browser_session: BrowserSession | None = None
		self.controller: Controller | None = None
		self.llm: ChatOpenAI | None = None
		self.file_system: FileSystem | None = None
		self._telemetry = ProductTelemetry()
		self._start_time = time.time()

		# Setup handlers
		self._setup_handlers()

	def _setup_handlers(self):
		"""Setup MCP server handlers."""

		@self.server.list_tools()
		async def handle_list_tools() -> list[types.Tool]:
			"""List all available browser-use tools."""
			return [
				# Agent tools
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
								'description': 'The index of the link or element to click (from browser_get_state)',
							},
							'new_tab': {
								'type': 'boolean',
								'description': 'Whether to open any resulting navigation in a new tab',
								'default': False,
							},
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
							'index': {
								'type': 'integer',
								'description': 'The index of the input element (from browser_get_state)',
							},
							'text': {'type': 'string', 'description': 'The text to type'},
						},
						'required': ['index', 'text'],
					},
				),
				types.Tool(
					name='browser_get_state',
					description='Get the current state of the page including all interactive elements',
					inputSchema={
						'type': 'object',
						'properties': {},
					},
				),
				types.Tool(
					name='browser_export_whole_webpage_as_pdf',
					description="Renders the entire webpage from a specific tab into a PDF file. This tool attempts to preserve the original visual layout, including background graphics. The PDF is saved to the specified 'file_path'. Returns the absolute path to the generated file.",
					inputSchema={
						'type': 'object',
						'properties': {
							'file_path': {
								'type': 'string',
								'description': 'The relative path to save the PDF file. It must end with .pdf.',
							},
							'tab_index': {
								'type': 'integer',
								'description': 'Index of the tab to export. Defaults to the current tab.',
								'default': None,
							},
						},
						'required': ['file_path'],
					},
				),
				# types.Tool(
				# 	name='browser_extract_content',
				# 	description='Extract structured content from the current page based on a query',
				# 	inputSchema={
				# 		'type': 'object',
				# 		'properties': {
				# 			'query': {'type': 'string', 'description': 'What information to extract from the page'},
				# 			'extract_links': {
				# 				'type': 'boolean',
				# 				'description': 'Whether to include links in the extraction',
				# 				'default': False,
				# 			},
				# 		},
				# 		'required': ['query'],
				# 	},
				# ),
				# types.Tool(
				# 	name='browser_scroll',
				# 	description='Scroll the page',
				# 	inputSchema={
				# 		'type': 'object',
				# 		'properties': {
				# 			'direction': {
				# 				'type': 'string',
				# 				'enum': ['up', 'down'],
				# 				'description': 'Direction to scroll',
				# 				'default': 'down',
				# 			}
				# 		},
				# 	},
				# ),
				types.Tool(
					name='browser_go_back',
					description='Go back to the previous page',
					inputSchema={'type': 'object', 'properties': {}},
				),
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
				# types.Tool(
				# 	name="browser_close",
				# 	description="Close the browser session",
				# 	inputSchema={
				# 		"type": "object",
				# 		"properties": {}
				# 	}
				# ),
				# types.Tool(
				# 	name='retry_with_browser_use_agent',
				# 	description='Retry a task using the browser-use agent. Only use this as a last resort if you fail to interact with a page multiple times.',
				# 	inputSchema={
				# 		'type': 'object',
				# 		'properties': {
				# 			'task': {
				# 				'type': 'string',
				# 				'description': 'The high-level goal and detailed step-by-step description of the task the AI browser agent needs to attempt, along with any relevant data needed to complete the task and info about previous attempts.',
				# 			},
				# 			'max_steps': {
				# 				'type': 'integer',
				# 				'description': 'Maximum number of steps the agent can take',
				# 				'default': 100,
				# 			},
				# 			'model': {
				# 				'type': 'string',
				# 				'description': 'LLM model to use (e.g., gpt-4o, claude-3-opus-20240229)',
				# 				'default': 'gpt-4o',
				# 			},
				# 			'allowed_domains': {
				# 				'type': 'array',
				# 				'items': {'type': 'string'},
				# 				'description': 'List of domains the agent is allowed to visit (security feature)',
				# 				'default': [],
				# 			},
				# 			'use_vision': {
				# 				'type': 'boolean',
				# 				'description': 'Whether to use vision capabilities (screenshots) for the agent',
				# 				'default': True,
				# 			},
				# 		},
				# 		'required': ['task'],
				# 	},
				# ),
			]

		@self.server.call_tool()
		async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
			"""Handle tool execution."""
			start_time = time.time()
			error_msg = None
			try:
				result = await self._execute_tool(name, arguments or {})
				return [types.TextContent(type='text', text=result)]
			except Exception as e:
				error_msg = str(e)
				logger.error(f'Tool execution failed: {e}', exc_info=True)
				return [types.TextContent(type='text', text=f'Error: {str(e)}')]
			finally:
				# Capture telemetry for tool calls
				duration = time.time() - start_time
				self._telemetry.capture(
					MCPServerTelemetryEvent(
						version=get_browser_use_version(),
						action='tool_call',
						tool_name=name,
						duration_seconds=duration,
						error_message=error_msg,
					)
				)

	async def _execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
		"""Execute a browser-use tool."""

		# Agent-based tools
		if tool_name == 'retry_with_browser_use_agent':
			return await self._retry_with_browser_use_agent(
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
				return await self._click(arguments['index'], arguments.get('new_tab', False))

			elif tool_name == 'browser_type':
				return await self._type_text(arguments['index'], arguments['text'])

			elif tool_name == 'browser_get_state':
				return await self._get_browser_state(arguments.get('include_screenshot', False))

			elif tool_name == 'browser_export_whole_webpage_as_pdf':
				return await self._export_whole_webpage_as_pdf(arguments['file_path'], arguments.get('tab_index', None))

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

	async def _init_browser_session(self, allowed_domains: list[str] | None = None, **kwargs):
		"""Initialize browser session using config"""
		if self.browser_session:
			return

		# Ensure all logging goes to stderr before browser initialization
		_ensure_all_loggers_use_stderr()

		logger.debug('Initializing browser session...')

		# Get profile config
		profile_config = get_default_profile(self.config)

		# Merge profile config with defaults and overrides
		profile_data = {
			'downloads_path': str(Path.home() / 'Downloads' / 'browser-use-mcp'),
			'wait_between_actions': 0.5,
			'keep_alive': True,
			'user_data_dir': '~/.config/browseruse/profiles/default',
			'is_mobile': False,
			'device_scale_factor': 1.0,
			'disable_security': False,
			'headless': False,
			'viewport_expansion': -1,
			**profile_config,  # Config values override defaults
		}

		# Tool parameter overrides (highest priority)
		if allowed_domains is not None:
			profile_data['allowed_domains'] = allowed_domains

		# Merge any additional kwargs that are valid BrowserProfile fields
		for key, value in kwargs.items():
			profile_data[key] = value

		# Create browser profile
		profile = BrowserProfile(**profile_data)

		# Create browser session
		self.browser_session = BrowserSession(browser_profile=profile)
		await self.browser_session.start()

		# Create controller for direct actions
		self.controller = Controller()

		# Initialize LLM from config
		llm_config = get_default_llm(self.config)
		if api_key := llm_config.get('api_key'):
			self.llm = ChatOpenAI(
				model=llm_config.get('model', 'gpt-4o-mini'),
				api_key=api_key,
				temperature=llm_config.get('temperature', 0.7),
				# max_tokens=llm_config.get('max_tokens'),
			)

		# Initialize FileSystem for extraction actions
		file_system_path = profile_config.get('file_system_path', '~/.browser-use-mcp')
		self.file_system = FileSystem(base_dir=Path(file_system_path).expanduser())

		logger.debug('Browser session initialized')

	async def _retry_with_browser_use_agent(
		self,
		task: str,
		max_steps: int = 100,
		model: str = 'gpt-4o',
		allowed_domains: list[str] | None = None,
		use_vision: bool = True,
	) -> str:
		"""Run an autonomous agent task."""
		logger.debug(f'Running agent task: {task}')

		# Get LLM config
		llm_config = get_default_llm(self.config)
		api_key = llm_config.get('api_key') or os.getenv('OPENAI_API_KEY')
		if not api_key:
			return 'Error: OPENAI_API_KEY not set in config or environment'

		# Override model if provided in tool call
		if model != llm_config.get('model', 'gpt-4o'):
			llm_model = model
		else:
			llm_model = llm_config.get('model', 'gpt-4o')

		llm = ChatOpenAI(
			model=llm_model,
			api_key=api_key,
			temperature=llm_config.get('temperature', 0.7),
		)

		# Get profile config and merge with tool parameters
		profile_config = get_default_profile(self.config)

		# Override allowed_domains if provided in tool call
		if allowed_domains is not None:
			profile_config['allowed_domains'] = allowed_domains

		# Create browser profile using config
		profile = BrowserProfile(**profile_config)

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
				# Filter out None values and convert to strings
				valid_urls = [str(url) for url in urls if url is not None]
				if valid_urls:
					results.append(f'\nURLs visited: {", ".join(valid_urls)}')

			return '\n'.join(results)

		except Exception as e:
			logger.error(f'Agent task failed: {e}', exc_info=True)
			return f'Agent task failed: {str(e)}'
		finally:
			# Clean up
			await agent.close()

	async def _navigate(self, url: str, new_tab: bool = False) -> str:
		"""Navigate to a URL."""
		if not self.browser_session:
			return 'Error: No browser session active'

		from browser_use.browser.events import NavigateToUrlEvent

		if new_tab:
			event = self.browser_session.event_bus.dispatch(NavigateToUrlEvent(url=url, new_tab=True))
			await event
			# Get the current tab count to determine the new tab index
			tabs = await self.browser_session.get_tabs()
			tab_index = len(tabs) - 1
			return f'Opened new tab #{tab_index} with URL: {url}'
		else:
			event = self.browser_session.event_bus.dispatch(NavigateToUrlEvent(url=url))
			await event
			return f'Navigated to: {url}'

	async def _click(self, index: int, new_tab: bool = False) -> str:
		"""Click an element by index."""
		if not self.browser_session:
			return 'Error: No browser session active'

		# Get the element
		element = await self.browser_session.get_dom_element_by_index(index)
		if not element:
			return f'Element with index {index} not found'

		if new_tab:
			# For links, extract href and open in new tab
			href = element.attributes.get('href')
			if href:
				# Convert relative href to absolute URL
				state = await self.browser_session.get_browser_state_summary()
				current_url = state.url
				if href.startswith('/'):
					# Relative URL - construct full URL
					from urllib.parse import urlparse

					parsed = urlparse(current_url)
					full_url = f'{parsed.scheme}://{parsed.netloc}{href}'
				else:
					full_url = href

				# Open link in new tab
				from browser_use.browser.events import NavigateToUrlEvent

				event = self.browser_session.event_bus.dispatch(NavigateToUrlEvent(url=full_url, new_tab=True))
				await event
				tabs = await self.browser_session.get_tabs()
				tab_index = len(tabs) - 1
				return f'Clicked element {index} and opened in new tab #{tab_index}'
			else:
				# For non-link elements, just do a normal click
				# Opening in new tab without href is not reliably supported
				from browser_use.browser.events import ClickElementEvent

				event = self.browser_session.event_bus.dispatch(ClickElementEvent(node=element))
				await event
				return f'Clicked element {index} (new tab not supported for non-link elements)'
		else:
			# Normal click
			from browser_use.browser.events import ClickElementEvent

			event = self.browser_session.event_bus.dispatch(ClickElementEvent(node=element))
			await event
			return f'Clicked element {index}'

	async def _type_text(self, index: int, text: str) -> str:
		"""Type text into an element."""
		if not self.browser_session:
			return 'Error: No browser session active'

		element = await self.browser_session.get_dom_element_by_index(index)
		if not element:
			return f'Element with index {index} not found'

		from browser_use.browser.events import TypeTextEvent

		event = self.browser_session.event_bus.dispatch(TypeTextEvent(node=element, text=text))
		await event
		return f"Typed '{text}' into element {index}"

	async def _get_browser_state(self, include_screenshot: bool = False) -> str:
		"""Get current browser state."""
		if not self.browser_session:
			return 'Error: No browser session active'

		state = await self.browser_session.get_browser_state_summary(cache_clickable_elements_hashes=False)
		await self.browser_session.remove_highlights()

		result = {
			'url': state.url,
			'title': state.title,
			'tabs': [{'url': tab.url, 'title': tab.title} for tab in state.tabs],
			'interactive_elements': [],
		}

		# Add interactive elements with their indices
		for index, element in state.dom_state.selector_map.items():
			elem_info = {
				'index': index,
				'tag': element.tag_name,
				'text': element.get_all_children_text(max_depth=2)[:100],
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

		if not self.browser_session:
			return 'Error: No browser session active'

		if not self.controller:
			return 'Error: Controller not initialized'

		state = await self.browser_session.get_browser_state_summary()

		# Use the extract_structured_data action
		# Create a dynamic action model that matches the controller's expectations
		from pydantic import create_model

		# Create action model dynamically
		ExtractAction = create_model(
			'ExtractAction',
			__base__=ActionModel,
			extract_structured_data=(dict[str, Any], {'query': query, 'extract_links': extract_links}),
		)

		action = ExtractAction()
		action_result = await self.controller.act(
			action=action,
			browser_session=self.browser_session,
			page_extraction_llm=self.llm,
			file_system=self.file_system,
		)

		return action_result.extracted_content or 'No content extracted'

	async def _scroll(self, direction: str = 'down') -> str:
		"""Scroll the page."""
		if not self.browser_session:
			return 'Error: No browser session active'

		from browser_use.browser.events import ScrollEvent

		# Scroll by a standard amount (500 pixels)
		event = self.browser_session.event_bus.dispatch(
			ScrollEvent(
				direction=direction,  # type: ignore
				amount=500,
			)
		)
		await event
		return f'Scrolled {direction}'

	async def _go_back(self) -> str:
		"""Go back in browser history."""
		if not self.browser_session:
			return 'Error: No browser session active'

		from browser_use.browser.events import GoBackEvent

		event = self.browser_session.event_bus.dispatch(GoBackEvent())
		await event
		return 'Navigated back'

	async def _close_browser(self) -> str:
		"""Close the browser session."""
		if self.browser_session:
			from browser_use.browser.events import BrowserStopEvent

			event = self.browser_session.event_bus.dispatch(BrowserStopEvent())
			await event
			self.browser_session = None
			self.controller = None
			return 'Browser closed'
		return 'No browser session to close'

	async def _list_tabs(self) -> str:
		"""List all open tabs."""
		if not self.browser_session:
			return 'Error: No browser session active'

		tabs_info = await self.browser_session.get_tabs()
		tabs = []
		for i, tab in enumerate(tabs_info):
			tabs.append({'index': i, 'url': tab.url, 'title': tab.title or ''})
		return json.dumps(tabs, indent=2)

	async def _switch_tab(self, tab_index: int) -> str:
		"""Switch to a different tab."""
		if not self.browser_session:
			return 'Error: No browser session active'

		from browser_use.browser.events import SwitchTabEvent

		event = self.browser_session.event_bus.dispatch(SwitchTabEvent(tab_index=tab_index))
		await event
		state = await self.browser_session.get_browser_state_summary()
		return f'Switched to tab {tab_index}: {state.url}'

	async def _close_tab(self, tab_index: int) -> str:
		"""Close a specific tab."""
		if not self.browser_session:
			return 'Error: No browser session active'

		tabs = await self.browser_session.get_tabs()
		if 0 <= tab_index < len(tabs):
			url = tabs[tab_index].url
			from browser_use.browser.events import CloseTabEvent

			event = self.browser_session.event_bus.dispatch(CloseTabEvent(tab_index=tab_index))
			await event
			return f'Closed tab {tab_index}: {url}'
		return f'Invalid tab index: {tab_index}'

	async def _scroll_to_bottom(self, tab):
		"""Use screen-by-screen scrolling with added delays to ensure lazy-loaded images are reliably triggered."""
		logger.debug('Starting to scroll page to load all content...')

		# Scrolling by the height of one screen at a time is more like human operation
		# and makes it easier to trigger lazy loading.
		viewport_height = await tab.evaluate('window.innerHeight')
		last_height = await tab.evaluate('document.body.scrollHeight')
		max_scroll_attempts = 1
		scroll_attempts = 0

		while True:
			await tab.evaluate(f'window.scrollBy(0, {viewport_height})')

			await asyncio.sleep(0.5)

			try:
				await tab.wait_for_load_state('networkidle', timeout=5000)
			except Exception:
				await asyncio.sleep(0.5)

			new_height = await tab.evaluate('document.body.scrollHeight')
			if new_height == last_height:
				scroll_attempts += 1
				if scroll_attempts >= max_scroll_attempts:
					logger.debug('Page height has not changed for several attempts. Assuming bottom of the page.')
					break
			else:
				scroll_attempts = 0

			last_height = new_height

		await tab.evaluate('window.scrollTo(0, document.body.scrollHeight)')
		await asyncio.sleep(2)
		logger.debug('Page scrolling finished.')

	async def _export_whole_webpage_as_pdf(self, file_path: str, tab_index: int | None = None) -> str:
		"""Export the whole webpage as a PDF file."""
		if not self.browser_session:
			return 'Error: Browser session not active'

		if not file_path.lower().endswith('.pdf'):
			return 'Error: File path must end with .pdf'

		await self.browser_session._wait_for_page_and_frames_load(timeout_overwrite=10.0)

		tab = None
		original_scroll_y = 0

		try:
			if tab_index is not None:
				if not (0 <= tab_index < len(self.browser_session.tabs)):
					return f'Error: Invalid tab index: {tab_index}'
				tab = self.browser_session.tabs[tab_index]
			else:
				tab = await self.browser_session.get_current_page()

			# step 1: Save the original scroll position for restoration later
			original_scroll_y = await tab.evaluate('window.scrollY')

			absolute_path = os.path.abspath(file_path)
			directory = os.path.dirname(absolute_path)
			if not os.path.exists(directory):
				os.makedirs(directory)

			# step 2: Scroll to the bottom of the page to ensure all lazy-loaded content is loaded
			await self._scroll_to_bottom(tab)

			# step 3: Emulate 'screen' media type for WYSIWYG layout
			await tab.emulate_media(media='screen')

			# step 4: Generate PDF
			await tab.pdf(path=absolute_path, print_background=True, scale=0.5)

			return absolute_path
		except Exception as e:
			logger.error(f'Failed to export PDF: {e}', exc_info=True)
			return f'Error: Failed to export PDF: {e}'
		finally:
			# step 5: Restore the original scroll position and viewport size
			if tab and not tab.is_closed():
				await tab.emulate_media(media=None)
				await tab.evaluate(f'window.scrollTo(0, {original_scroll_y})')
				logger.debug(f'Restored the original scroll position to {original_scroll_y}px')

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

	async def run_http(self, port: int = 3000, json_response: bool = False):
		"""Run the MCP server over Streamable HTTP."""
		session_manager = StreamableHTTPSessionManager(
			app=self.server,
			event_store=None,
			json_response=json_response,
			stateless=True,
		)

		async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
			await session_manager.handle_request(scope, receive, send)

		@contextlib.asynccontextmanager
		async def lifespan(app: Starlette):
			async with session_manager.run():
				logger.info('BrowserUseServer started in Streamable HTTP mode')
				yield

		starlette_app = Starlette(
			debug=False,
			routes=[
				Mount('/mcp', app=handle_streamable_http),
			],
			lifespan=lifespan,
		)

		import uvicorn

		config = uvicorn.Config(starlette_app, host='127.0.0.1', port=port, loop='asyncio')
		server = uvicorn.Server(config)
		await server.serve()


async def main(http: bool = False, port: int = 3000, json_response: bool = False):
	if not MCP_AVAILABLE:
		print('MCP SDK is required. Install with: pip install mcp', file=sys.stderr)
		sys.exit(1)

	server = BrowserUseServer()
	server._telemetry.capture(
		MCPServerTelemetryEvent(
			version=get_browser_use_version(),
			action='start',
			parent_process_cmdline=get_parent_process_cmdline(),
		)
	)

	try:
		if http:
			await server.run_http(port=port, json_response=json_response)
		else:
			await server.run()
	finally:
		duration = time.time() - server._start_time
		server._telemetry.capture(
			MCPServerTelemetryEvent(
				version=get_browser_use_version(),
				action='stop',
				duration_seconds=duration,
				parent_process_cmdline=get_parent_process_cmdline(),
			)
		)
		server._telemetry.flush()


if __name__ == '__main__':
	import argparse

	parser = argparse.ArgumentParser()
	parser.add_argument('--http', action='store_true', help='Run in Streamable HTTP mode instead of stdio')
	parser.add_argument('--port', type=int, default=3000, help='HTTP port (only in HTTP mode)')
	parser.add_argument('--json-response', action='store_true', help='Use JSON responses instead of SSE')
	args = parser.parse_args()

	asyncio.run(main(http=args.http, port=args.port, json_response=args.json_response))
