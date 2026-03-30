"""MCP Server for browser-use - exposes browser control primitives via Model Context Protocol.

Any MCP-compatible AI (Claude, ChatGPT, Gemini, etc.) can use this server to control
a real web browser. No internal LLM required - the calling AI makes all decisions.

Tools provided:
- Navigation: navigate, go_back, scroll, wait
- Interaction: click, type, send_keys, select_option
- Observation: get_state, screenshot, extract_content, get_html
- Tabs: list_tabs, switch_tab, close_tab
- Sessions: list_sessions, close_session, close_all

Usage:
    uvx browser-use --mcp

Or configure in any MCP client:
    {
        "mcpServers": {
            "browser-use": {
                "command": "uvx",
                "args": ["browser-use[cli]", "--mcp"]
            }
        }
    }
"""

import os
import sys

# Set environment variables BEFORE any browser_use imports to prevent early logging
os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'critical'
os.environ['BROWSER_USE_SETUP_LOGGING'] = 'false'

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

# Configure logging for MCP mode - redirect to stderr but preserve critical diagnostics
logging.basicConfig(
	stream=sys.stderr, level=logging.WARNING, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', force=True
)

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
	os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'warning'
	os.environ['BROWSER_USE_SETUP_LOGGING'] = 'false'  # Prevent automatic logging setup

	# Configure logging to stderr for MCP mode - preserve warnings and above for troubleshooting
	setup_logging(stream=sys.stderr, log_level='warning', force_setup=True)

	# Also configure the root logger and all existing loggers to use stderr
	logging.root.handlers = []
	stderr_handler = logging.StreamHandler(sys.stderr)
	stderr_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
	logging.root.addHandler(stderr_handler)
	logging.root.setLevel(logging.CRITICAL)

	# Configure all existing loggers to use stderr and CRITICAL level
	for name in list(logging.root.manager.loggerDict.keys()):
		logger_obj = logging.getLogger(name)
		logger_obj.handlers = []
		logger_obj.setLevel(logging.CRITICAL)
		logger_obj.addHandler(stderr_handler)
		logger_obj.propagate = False


# Configure MCP server logging before any browser_use imports to capture early log lines
_configure_mcp_server_logging()

# Additional suppression - disable all logging completely for MCP mode
logging.disable(logging.CRITICAL)

# Import browser_use modules
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.config import get_default_profile, load_browser_use_config

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
	logging.root.setLevel(logging.CRITICAL)

	# Configure all existing loggers
	for name in list(logging.root.manager.loggerDict.keys()):
		logger_obj = logging.getLogger(name)
		logger_obj.handlers = [stderr_handler]
		logger_obj.setLevel(logging.CRITICAL)
		logger_obj.propagate = False


# Ensure stderr logging after all imports
_ensure_all_loggers_use_stderr()


# Try to import MCP SDK
try:
	import mcp.server.stdio
	import mcp.types as types
	from mcp.server import NotificationOptions, Server
	from mcp.server.models import InitializationOptions

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
from browser_use.utils import create_task_with_error_handling, get_browser_use_version


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

	def __init__(self, session_timeout_minutes: int = 10):
		# Ensure all logging goes to stderr (in case new loggers were created)
		_ensure_all_loggers_use_stderr()

		self.server = Server('browser-use')
		self.config = load_browser_use_config()
		self.browser_session: BrowserSession | None = None
		self._telemetry = ProductTelemetry()
		self._cookie_storage_path = Path.home() / '.config' / 'browseruse' / 'cookies' / 'storage_state.json'
		self._start_time = time.time()

		# Session management
		self.active_sessions: dict[str, dict[str, Any]] = {}  # session_id -> session info
		self.session_timeout_minutes = session_timeout_minutes
		self._cleanup_task: Any = None

		# Setup handlers
		self._setup_handlers()

	def _setup_handlers(self):
		"""Setup MCP server handlers."""

		@self.server.list_tools()
		async def handle_list_tools() -> list[types.Tool]:
			"""List all available browser-use tools."""
			return [
				# Browser control tools
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
					description='Click an element by index or at specific viewport coordinates. Use index for elements from browser_get_state, or coordinate_x/coordinate_y for pixel-precise clicking.',
					inputSchema={
						'type': 'object',
						'properties': {
							'index': {
								'type': 'integer',
								'description': 'The index of the element to click (from browser_get_state). Provide this OR coordinate_x+coordinate_y.',
							},
							'coordinate_x': {
								'type': 'integer',
								'description': 'X coordinate in pixels from the left edge of the viewport. Must be used together with coordinate_y. Provide this OR index.',
							},
							'coordinate_y': {
								'type': 'integer',
								'description': 'Y coordinate in pixels from the top edge of the viewport. Must be used together with coordinate_x. Provide this OR index.',
							},
							'new_tab': {
								'type': 'boolean',
								'description': 'Whether to open any resulting navigation in a new tab',
								'default': False,
							},
						},
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
						'properties': {
							'include_screenshot': {
								'type': 'boolean',
								'description': 'Whether to include a screenshot of the current page',
								'default': False,
							}
						},
					},
				),
				types.Tool(
					name='browser_extract_content',
					description='Extract the text content of the current page as clean markdown. Useful for reading articles, getting page text, etc.',
					inputSchema={
						'type': 'object',
						'properties': {
							'extract_links': {
								'type': 'boolean',
								'description': 'Whether to include links in the extraction',
								'default': False,
							},
						},
					},
				),
				types.Tool(
					name='browser_get_html',
					description='Get the raw HTML of the current page or a specific element by CSS selector',
					inputSchema={
						'type': 'object',
						'properties': {
							'selector': {
								'type': 'string',
								'description': 'Optional CSS selector to get HTML of a specific element. If omitted, returns full page HTML.',
							},
						},
					},
				),
				types.Tool(
					name='browser_screenshot',
					description='Take a screenshot of the current page. Returns viewport metadata as text and the screenshot as an image.',
					inputSchema={
						'type': 'object',
						'properties': {
							'full_page': {
								'type': 'boolean',
								'description': 'Whether to capture the full scrollable page or just the visible viewport',
								'default': False,
							},
						},
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
				# Tab management
				types.Tool(
					name='browser_list_tabs', description='List all open tabs', inputSchema={'type': 'object', 'properties': {}}
				),
				types.Tool(
					name='browser_switch_tab',
					description='Switch to a different tab',
					inputSchema={
						'type': 'object',
						'properties': {'tab_id': {'type': 'string', 'description': '4 Character Tab ID of the tab to switch to'}},
						'required': ['tab_id'],
					},
				),
				types.Tool(
					name='browser_close_tab',
					description='Close a tab',
					inputSchema={
						'type': 'object',
						'properties': {'tab_id': {'type': 'string', 'description': '4 Character Tab ID of the tab to close'}},
						'required': ['tab_id'],
					},
				),
				types.Tool(
					name='browser_send_keys',
					description='Send keyboard keys or shortcuts. Examples: "Enter", "Escape", "Tab", "Backspace", "ctrl+a", "cmd+c", "ArrowDown", "Space".',
					inputSchema={
						'type': 'object',
						'properties': {
							'keys': {
								'type': 'string',
								'description': 'The key or key combination to send (e.g., "Enter", "ctrl+a", "cmd+c", "Escape", "Tab", "ArrowDown")',
							},
						},
						'required': ['keys'],
					},
				),
				types.Tool(
					name='browser_select_option',
					description='Select an option from a dropdown/select element by its visible text',
					inputSchema={
						'type': 'object',
						'properties': {
							'index': {
								'type': 'integer',
								'description': 'The index of the dropdown element (from browser_get_state)',
							},
							'text': {
								'type': 'string',
								'description': 'The visible text of the option to select',
							},
						},
						'required': ['index', 'text'],
					},
				),
				types.Tool(
					name='browser_get_dropdown_options',
					description='Get all available options from a dropdown/select element',
					inputSchema={
						'type': 'object',
						'properties': {
							'index': {
								'type': 'integer',
								'description': 'The index of the dropdown element (from browser_get_state)',
							},
						},
						'required': ['index'],
					},
				),
				types.Tool(
					name='browser_wait',
					description='Wait for a specified number of seconds. Useful for waiting for page load, animations, or dynamic content.',
					inputSchema={
						'type': 'object',
						'properties': {
							'seconds': {
								'type': 'number',
								'description': 'Number of seconds to wait (0.5 to 30)',
								'default': 2,
							},
						},
					},
				),
				# Browser session management tools
				types.Tool(
					name='browser_list_sessions',
					description='List all active browser sessions with their details and last activity time',
					inputSchema={'type': 'object', 'properties': {}},
				),
				types.Tool(
					name='browser_close_session',
					description='Close a specific browser session by its ID',
					inputSchema={
						'type': 'object',
						'properties': {
							'session_id': {
								'type': 'string',
								'description': 'The browser session ID to close (get from browser_list_sessions)',
							}
						},
						'required': ['session_id'],
					},
				),
				types.Tool(
					name='browser_close_all',
					description='Close all active browser sessions and clean up resources',
					inputSchema={'type': 'object', 'properties': {}},
				),
				# Cookie management tools
				types.Tool(
					name='browser_get_cookies',
					description='Get all cookies for the current browser session. Optionally filter by domain.',
					inputSchema={
						'type': 'object',
						'properties': {
							'domain': {
								'type': 'string',
								'description': 'Optional domain to filter cookies (e.g., "github.com")',
							},
						},
					},
				),
				types.Tool(
					name='browser_set_cookies',
					description='Set one or more cookies in the browser. Each cookie needs at least name, value, and domain.',
					inputSchema={
						'type': 'object',
						'properties': {
							'cookies': {
								'type': 'array',
								'description': 'List of cookies to set',
								'items': {
									'type': 'object',
									'properties': {
										'name': {'type': 'string', 'description': 'Cookie name'},
										'value': {'type': 'string', 'description': 'Cookie value'},
										'domain': {'type': 'string', 'description': 'Cookie domain (e.g., ".github.com")'},
										'path': {'type': 'string', 'description': 'Cookie path', 'default': '/'},
										'secure': {'type': 'boolean', 'description': 'Secure flag', 'default': False},
										'httpOnly': {'type': 'boolean', 'description': 'HttpOnly flag', 'default': False},
										'sameSite': {
											'type': 'string',
											'enum': ['Lax', 'Strict', 'None'],
											'description': 'SameSite policy',
											'default': 'Lax',
										},
									},
									'required': ['name', 'value', 'domain'],
								},
							},
						},
						'required': ['cookies'],
					},
				),
				types.Tool(
					name='browser_clear_cookies',
					description='Clear all cookies in the browser, or only cookies for a specific domain',
					inputSchema={
						'type': 'object',
						'properties': {
							'domain': {
								'type': 'string',
								'description': 'Optional domain to clear cookies for. If omitted, clears all cookies.',
							},
						},
					},
				),
				types.Tool(
					name='browser_save_storage_state',
					description='Save current cookies and localStorage to disk for persistence across sessions. Cookies are auto-saved periodically, but use this to force an immediate save.',
					inputSchema={'type': 'object', 'properties': {}},
				),
			]

		@self.server.list_resources()
		async def handle_list_resources() -> list[types.Resource]:
			"""List available resources (none for browser-use)."""
			return []

		@self.server.list_prompts()
		async def handle_list_prompts() -> list[types.Prompt]:
			"""List available prompts (none for browser-use)."""
			return []

		@self.server.call_tool()
		async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent | types.ImageContent]:
			"""Handle tool execution."""
			start_time = time.time()
			error_msg = None
			try:
				result = await self._execute_tool(name, arguments or {})
				if isinstance(result, list):
					return result
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

	async def _execute_tool(
		self, tool_name: str, arguments: dict[str, Any]
	) -> str | list[types.TextContent | types.ImageContent]:
		"""Execute a browser-use tool. Returns str for most tools, or a content list for tools with image output."""

		# Browser session management tools (don't require active session)
		if tool_name == 'browser_list_sessions':
			return await self._list_sessions()

		elif tool_name == 'browser_close_session':
			return await self._close_session(arguments['session_id'])

		elif tool_name == 'browser_close_all':
			return await self._close_all_sessions()

		# Direct browser control tools (require active session)
		elif tool_name.startswith('browser_'):
			# Ensure browser session exists
			if not self.browser_session:
				await self._init_browser_session()

			if tool_name == 'browser_navigate':
				return await self._navigate(arguments['url'], arguments.get('new_tab', False))

			elif tool_name == 'browser_click':
				return await self._click(
					index=arguments.get('index'),
					coordinate_x=arguments.get('coordinate_x'),
					coordinate_y=arguments.get('coordinate_y'),
					new_tab=arguments.get('new_tab', False),
				)

			elif tool_name == 'browser_type':
				return await self._type_text(arguments['index'], arguments['text'])

			elif tool_name == 'browser_get_state':
				state_json, screenshot_b64 = await self._get_browser_state(arguments.get('include_screenshot', False))
				content: list[types.TextContent | types.ImageContent] = [types.TextContent(type='text', text=state_json)]
				if screenshot_b64:
					content.append(types.ImageContent(type='image', data=screenshot_b64, mimeType='image/png'))
				return content

			elif tool_name == 'browser_get_html':
				return await self._get_html(arguments.get('selector'))

			elif tool_name == 'browser_screenshot':
				meta_json, screenshot_b64 = await self._screenshot(arguments.get('full_page', False))
				content: list[types.TextContent | types.ImageContent] = [types.TextContent(type='text', text=meta_json)]
				if screenshot_b64:
					content.append(types.ImageContent(type='image', data=screenshot_b64, mimeType='image/png'))
				return content

			elif tool_name == 'browser_extract_content':
				return await self._extract_content(arguments.get('extract_links', False))

			elif tool_name == 'browser_scroll':
				return await self._scroll(arguments.get('direction', 'down'))

			elif tool_name == 'browser_go_back':
				return await self._go_back()

			elif tool_name == 'browser_close':
				return await self._close_browser()

			elif tool_name == 'browser_list_tabs':
				return await self._list_tabs()

			elif tool_name == 'browser_switch_tab':
				return await self._switch_tab(arguments['tab_id'])

			elif tool_name == 'browser_close_tab':
				return await self._close_tab(arguments['tab_id'])

			elif tool_name == 'browser_send_keys':
				return await self._send_keys(arguments['keys'])

			elif tool_name == 'browser_select_option':
				return await self._select_option(arguments['index'], arguments['text'])

			elif tool_name == 'browser_get_dropdown_options':
				return await self._get_dropdown_options(arguments['index'])

			elif tool_name == 'browser_wait':
				return await self._wait(arguments.get('seconds', 2))

			elif tool_name == 'browser_get_cookies':
				return await self._get_cookies(arguments.get('domain'))

			elif tool_name == 'browser_set_cookies':
				return await self._set_cookies(arguments['cookies'])

			elif tool_name == 'browser_clear_cookies':
				return await self._clear_cookies(arguments.get('domain'))

			elif tool_name == 'browser_save_storage_state':
				return await self._save_storage_state()

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

		# Default cookie storage path
		cookie_dir = Path.home() / '.config' / 'browseruse' / 'cookies'
		cookie_dir.mkdir(parents=True, exist_ok=True)
		self._cookie_storage_path = cookie_dir / 'storage_state.json'

		# Merge profile config with defaults and overrides
		profile_data = {
			'downloads_path': str(Path.home() / 'Downloads' / 'browser-use-mcp'),
			'wait_between_actions': 0.5,
			'keep_alive': True,
			'user_data_dir': '~/.config/browseruse/profiles/default',
			'device_scale_factor': 1.0,
			'disable_security': False,
			'headless': False,
			'storage_state': str(self._cookie_storage_path),
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

		# Track the session for management
		self._track_session(self.browser_session)

		logger.debug('Browser session initialized')

	async def _navigate(self, url: str, new_tab: bool = False) -> str:
		"""Navigate to a URL."""
		if not self.browser_session:
			return 'Error: No browser session active'

		# Update session activity
		self._update_session_activity(self.browser_session.id)

		from browser_use.browser.events import NavigateToUrlEvent

		if new_tab:
			event = self.browser_session.event_bus.dispatch(NavigateToUrlEvent(url=url, new_tab=True))
			await event
			return f'Opened new tab with URL: {url}'
		else:
			event = self.browser_session.event_bus.dispatch(NavigateToUrlEvent(url=url))
			await event
			return f'Navigated to: {url}'

	async def _click(
		self,
		index: int | None = None,
		coordinate_x: int | None = None,
		coordinate_y: int | None = None,
		new_tab: bool = False,
	) -> str:
		"""Click an element by index or at viewport coordinates."""
		if not self.browser_session:
			return 'Error: No browser session active'

		# Update session activity
		self._update_session_activity(self.browser_session.id)

		# Coordinate-based clicking
		if coordinate_x is not None and coordinate_y is not None:
			from browser_use.browser.events import ClickCoordinateEvent

			event = self.browser_session.event_bus.dispatch(
				ClickCoordinateEvent(coordinate_x=coordinate_x, coordinate_y=coordinate_y)
			)
			await event
			return f'Clicked at coordinates ({coordinate_x}, {coordinate_y})'

		# Index-based clicking
		if index is None:
			return 'Error: Provide either index or both coordinate_x and coordinate_y'

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
				return f'Clicked element {index} and opened in new tab {full_url[:20]}...'
			else:
				# For non-link elements, just do a normal click
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

		# Conservative heuristic to detect potentially sensitive data
		# Only flag very obvious patterns to minimize false positives
		is_potentially_sensitive = len(text) >= 6 and (
			# Email pattern: contains @ and a domain-like suffix
			('@' in text and '.' in text.split('@')[-1] if '@' in text else False)
			# Mixed alphanumeric with reasonable complexity (likely API keys/tokens)
			or (
				len(text) >= 16
				and any(char.isdigit() for char in text)
				and any(char.isalpha() for char in text)
				and any(char in '.-_' for char in text)
			)
		)

		# Use generic key names to avoid information leakage about detection patterns
		sensitive_key_name = None
		if is_potentially_sensitive:
			if '@' in text and '.' in text.split('@')[-1]:
				sensitive_key_name = 'email'
			else:
				sensitive_key_name = 'credential'

		event = self.browser_session.event_bus.dispatch(
			TypeTextEvent(node=element, text=text, is_sensitive=is_potentially_sensitive, sensitive_key_name=sensitive_key_name)
		)
		await event

		if is_potentially_sensitive:
			if sensitive_key_name:
				return f'Typed <{sensitive_key_name}> into element {index}'
			else:
				return f'Typed <sensitive> into element {index}'
		else:
			return f"Typed '{text}' into element {index}"

	async def _get_browser_state(self, include_screenshot: bool = False) -> tuple[str, str | None]:
		"""Get current browser state. Returns (state_json, screenshot_b64 | None)."""
		if not self.browser_session:
			return 'Error: No browser session active', None

		state = await self.browser_session.get_browser_state_summary()

		result: dict[str, Any] = {
			'url': state.url,
			'title': state.title,
			'tabs': [{'url': tab.url, 'title': tab.title} for tab in state.tabs],
			'interactive_elements': [],
		}

		# Add viewport info so the LLM knows the coordinate space
		if state.page_info:
			pi = state.page_info
			result['viewport'] = {
				'width': pi.viewport_width,
				'height': pi.viewport_height,
			}
			result['page'] = {
				'width': pi.page_width,
				'height': pi.page_height,
			}
			result['scroll'] = {
				'x': pi.scroll_x,
				'y': pi.scroll_y,
			}

		# Add interactive elements with their indices
		for index, element in state.dom_state.selector_map.items():
			elem_info: dict[str, Any] = {
				'index': index,
				'tag': element.tag_name,
				'text': element.get_all_children_text(max_depth=2)[:100],
			}
			if element.attributes.get('placeholder'):
				elem_info['placeholder'] = element.attributes['placeholder']
			if element.attributes.get('href'):
				elem_info['href'] = element.attributes['href']
			result['interactive_elements'].append(elem_info)

		# Return screenshot separately as ImageContent instead of embedding base64 in JSON
		screenshot_b64 = None
		if include_screenshot and state.screenshot:
			screenshot_b64 = state.screenshot
			# Include viewport dimensions in JSON so LLM can map pixels to coordinates
			if state.page_info:
				result['screenshot_dimensions'] = {
					'width': state.page_info.viewport_width,
					'height': state.page_info.viewport_height,
				}

		return json.dumps(result, indent=2), screenshot_b64

	async def _get_html(self, selector: str | None = None) -> str:
		"""Get raw HTML of the page or a specific element."""
		if not self.browser_session:
			return 'Error: No browser session active'

		self._update_session_activity(self.browser_session.id)

		cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None, focus=False)
		if not cdp_session:
			return 'Error: No active CDP session'

		if selector:
			js = (
				f'(function(){{ const el = document.querySelector({json.dumps(selector)}); return el ? el.outerHTML : null; }})()'
			)
		else:
			js = 'document.documentElement.outerHTML'

		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': js, 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		html = result.get('result', {}).get('value')
		if html is None:
			return f'No element found for selector: {selector}' if selector else 'Error: Could not get page HTML'
		return html

	async def _screenshot(self, full_page: bool = False) -> tuple[str, str | None]:
		"""Take a screenshot. Returns (metadata_json, screenshot_b64 | None)."""
		if not self.browser_session:
			return 'Error: No browser session active', None

		import base64

		self._update_session_activity(self.browser_session.id)

		data = await self.browser_session.take_screenshot(full_page=full_page)
		b64 = base64.b64encode(data).decode()

		# Return screenshot separately as ImageContent instead of embedding base64 in JSON
		state = await self.browser_session.get_browser_state_summary()
		result: dict[str, Any] = {
			'size_bytes': len(data),
		}
		if state.page_info:
			result['viewport'] = {
				'width': state.page_info.viewport_width,
				'height': state.page_info.viewport_height,
			}
		return json.dumps(result), b64

	async def _extract_content(self, extract_links: bool = False) -> str:
		"""Extract page content as clean markdown without using LLM."""
		if not self.browser_session:
			return 'Error: No browser session active'

		self._update_session_activity(self.browser_session.id)

		from browser_use.dom.markdown_extractor import extract_clean_markdown

		try:
			markdown_text, metadata = await extract_clean_markdown(
				browser_session=self.browser_session,
				extract_links=extract_links,
			)
			return markdown_text or 'No content extracted'
		except Exception as e:
			logger.error(f'Content extraction failed: {e}')
			return f'Error extracting content: {str(e)}'

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
			return 'Browser closed'
		return 'No browser session to close'

	async def _list_tabs(self) -> str:
		"""List all open tabs."""
		if not self.browser_session:
			return 'Error: No browser session active'

		tabs_info = await self.browser_session.get_tabs()
		tabs = []
		for i, tab in enumerate(tabs_info):
			tabs.append({'tab_id': tab.target_id[-4:], 'url': tab.url, 'title': tab.title or ''})
		return json.dumps(tabs, indent=2)

	async def _switch_tab(self, tab_id: str) -> str:
		"""Switch to a different tab."""
		if not self.browser_session:
			return 'Error: No browser session active'

		from browser_use.browser.events import SwitchTabEvent

		target_id = await self.browser_session.get_target_id_from_tab_id(tab_id)
		event = self.browser_session.event_bus.dispatch(SwitchTabEvent(target_id=target_id))
		await event
		state = await self.browser_session.get_browser_state_summary()
		return f'Switched to tab {tab_id}: {state.url}'

	async def _close_tab(self, tab_id: str) -> str:
		"""Close a specific tab."""
		if not self.browser_session:
			return 'Error: No browser session active'

		from browser_use.browser.events import CloseTabEvent

		target_id = await self.browser_session.get_target_id_from_tab_id(tab_id)
		event = self.browser_session.event_bus.dispatch(CloseTabEvent(target_id=target_id))
		await event
		current_url = await self.browser_session.get_current_page_url()
		return f'Closed tab # {tab_id}, now on {current_url}'

	async def _send_keys(self, keys: str) -> str:
		"""Send keyboard keys or shortcuts."""
		if not self.browser_session:
			return 'Error: No browser session active'

		self._update_session_activity(self.browser_session.id)

		from browser_use.browser.events import SendKeysEvent

		event = self.browser_session.event_bus.dispatch(SendKeysEvent(keys=keys))
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)
		return f'Sent keys: {keys}'

	async def _select_option(self, index: int, text: str) -> str:
		"""Select an option from a dropdown element."""
		if not self.browser_session:
			return 'Error: No browser session active'

		self._update_session_activity(self.browser_session.id)

		element = await self.browser_session.get_dom_element_by_index(index)
		if not element:
			return f'Element with index {index} not found'

		from browser_use.browser.events import SelectDropdownOptionEvent

		event = self.browser_session.event_bus.dispatch(SelectDropdownOptionEvent(node=element, text=text))
		await event
		result = await event.event_result(raise_if_any=True, raise_if_none=False)
		return f'Selected option "{text}" in element {index}'

	async def _get_dropdown_options(self, index: int) -> str:
		"""Get all options from a dropdown element."""
		if not self.browser_session:
			return 'Error: No browser session active'

		self._update_session_activity(self.browser_session.id)

		element = await self.browser_session.get_dom_element_by_index(index)
		if not element:
			return f'Element with index {index} not found'

		from browser_use.browser.events import GetDropdownOptionsEvent

		event = self.browser_session.event_bus.dispatch(GetDropdownOptionsEvent(node=element))
		await event
		result = await event.event_result(raise_if_any=True, raise_if_none=False)
		if result:
			return json.dumps(result, indent=2)
		return 'No options found'

	async def _wait(self, seconds: float = 2) -> str:
		"""Wait for specified seconds."""
		# Clamp to reasonable range
		seconds = max(0.5, min(seconds, 30))

		from browser_use.browser.events import WaitEvent

		if self.browser_session:
			self._update_session_activity(self.browser_session.id)
			event = self.browser_session.event_bus.dispatch(WaitEvent(seconds=seconds))
			await event
		else:
			await asyncio.sleep(seconds)

		return f'Waited {seconds} seconds'

	async def _get_cookies(self, domain: str | None = None) -> str:
		"""Get cookies, optionally filtered by domain."""
		if not self.browser_session:
			return 'Error: No browser session active'

		self._update_session_activity(self.browser_session.id)

		try:
			cookies = await self.browser_session._cdp_get_cookies()
			cookie_list = [
				{
					'name': c['name'],
					'value': c['value'],
					'domain': c['domain'],
					'path': c.get('path', '/'),
					'secure': c.get('secure', False),
					'httpOnly': c.get('httpOnly', False),
					'sameSite': c.get('sameSite', 'Lax'),
					'expires': c.get('expires', -1),
				}
				for c in cookies
			]

			# Filter by domain if specified
			if domain:
				cookie_list = [c for c in cookie_list if domain in c['domain'] or c['domain'].endswith('.' + domain)]

			return json.dumps(cookie_list, indent=2)
		except Exception as e:
			logger.error(f'Failed to get cookies: {e}')
			return f'Error getting cookies: {str(e)}'

	async def _set_cookies(self, cookies: list[dict[str, Any]]) -> str:
		"""Set cookies in the browser."""
		if not self.browser_session:
			return 'Error: No browser session active'

		self._update_session_activity(self.browser_session.id)

		try:
			cdp_cookies = [
				{
					'name': c['name'],
					'value': c['value'],
					'domain': c['domain'],
					'path': c.get('path', '/'),
					'secure': c.get('secure', False),
					'httpOnly': c.get('httpOnly', False),
					'sameSite': c.get('sameSite', 'Lax'),
				}
				for c in cookies
			]
			await self.browser_session._cdp_set_cookies(cdp_cookies)  # type: ignore[arg-type]
			return f'Successfully set {len(cdp_cookies)} cookie(s)'
		except Exception as e:
			logger.error(f'Failed to set cookies: {e}')
			return f'Error setting cookies: {str(e)}'

	async def _clear_cookies(self, domain: str | None = None) -> str:
		"""Clear cookies, optionally for a specific domain."""
		if not self.browser_session:
			return 'Error: No browser session active'

		self._update_session_activity(self.browser_session.id)

		try:
			if domain:
				# Get all cookies, remove matching domain, re-set the rest
				cookies = await self.browser_session._cdp_get_cookies()
				remaining = [c for c in cookies if domain not in c.get('domain', '') and not c.get('domain', '').endswith('.' + domain)]
				await self.browser_session._cdp_clear_cookies()
				if remaining:
					await self.browser_session._cdp_set_cookies(remaining)
				return f'Cleared cookies for domain: {domain}'
			else:
				await self.browser_session.clear_cookies()
				return 'Cleared all cookies'
		except Exception as e:
			logger.error(f'Failed to clear cookies: {e}')
			return f'Error clearing cookies: {str(e)}'

	async def _save_storage_state(self) -> str:
		"""Force save current storage state (cookies + localStorage) to disk."""
		if not self.browser_session:
			return 'Error: No browser session active'

		self._update_session_activity(self.browser_session.id)

		try:
			from browser_use.browser.events import SaveStorageStateEvent

			event = self.browser_session.event_bus.dispatch(SaveStorageStateEvent())
			await event
			result = await event.event_result(raise_if_any=True, raise_if_none=False)

			cookie_path = getattr(self, '_cookie_storage_path', 'default location')
			return f'Storage state saved to {cookie_path}'
		except Exception as e:
			# Fallback: use export_storage_state directly
			try:
				cookie_path = getattr(self, '_cookie_storage_path', None)
				if cookie_path:
					await self.browser_session.export_storage_state(output_path=cookie_path)
					return f'Storage state exported to {cookie_path}'
				else:
					return 'Error: No storage path configured'
			except Exception as e2:
				logger.error(f'Failed to save storage state: {e2}')
				return f'Error saving storage state: {str(e2)}'

	def _track_session(self, session: BrowserSession) -> None:
		"""Track a browser session for management."""
		self.active_sessions[session.id] = {
			'session': session,
			'created_at': time.time(),
			'last_activity': time.time(),
			'url': getattr(session, 'current_url', None),
		}

	def _update_session_activity(self, session_id: str) -> None:
		"""Update the last activity time for a session."""
		if session_id in self.active_sessions:
			self.active_sessions[session_id]['last_activity'] = time.time()

	async def _list_sessions(self) -> str:
		"""List all active browser sessions."""
		if not self.active_sessions:
			return 'No active browser sessions'

		sessions_info = []
		for session_id, session_data in self.active_sessions.items():
			session = session_data['session']
			created_at = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(session_data['created_at']))
			last_activity = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(session_data['last_activity']))

			# Check if session is still active
			is_active = hasattr(session, 'cdp_client') and session.cdp_client is not None

			sessions_info.append(
				{
					'session_id': session_id,
					'created_at': created_at,
					'last_activity': last_activity,
					'active': is_active,
					'current_url': session_data.get('url', 'Unknown'),
					'age_minutes': (time.time() - session_data['created_at']) / 60,
				}
			)

		return json.dumps(sessions_info, indent=2)

	async def _close_session(self, session_id: str) -> str:
		"""Close a specific browser session."""
		if session_id not in self.active_sessions:
			return f'Session {session_id} not found'

		session_data = self.active_sessions[session_id]
		session = session_data['session']

		try:
			# Close the session
			if hasattr(session, 'kill'):
				await session.kill()
			elif hasattr(session, 'close'):
				await session.close()

			# Remove from tracking
			del self.active_sessions[session_id]

			# If this was the current session, clear it
			if self.browser_session and self.browser_session.id == session_id:
				self.browser_session = None

			return f'Successfully closed session {session_id}'
		except Exception as e:
			return f'Error closing session {session_id}: {str(e)}'

	async def _close_all_sessions(self) -> str:
		"""Close all active browser sessions."""
		if not self.active_sessions:
			return 'No active sessions to close'

		closed_count = 0
		errors = []

		for session_id in list(self.active_sessions.keys()):
			try:
				result = await self._close_session(session_id)
				if 'Successfully closed' in result:
					closed_count += 1
				else:
					errors.append(f'{session_id}: {result}')
			except Exception as e:
				errors.append(f'{session_id}: {str(e)}')

		# Clear current session references
		self.browser_session = None

		result = f'Closed {closed_count} sessions'
		if errors:
			result += f'. Errors: {"; ".join(errors)}'

		return result

	async def _cleanup_expired_sessions(self) -> None:
		"""Background task to clean up expired sessions."""
		current_time = time.time()
		timeout_seconds = self.session_timeout_minutes * 60

		expired_sessions = []
		for session_id, session_data in self.active_sessions.items():
			last_activity = session_data['last_activity']
			if current_time - last_activity > timeout_seconds:
				expired_sessions.append(session_id)

		for session_id in expired_sessions:
			try:
				await self._close_session(session_id)
				logger.info(f'Auto-closed expired session {session_id}')
			except Exception as e:
				logger.error(f'Error auto-closing session {session_id}: {e}')

	async def _start_cleanup_task(self) -> None:
		"""Start the background cleanup task."""

		async def cleanup_loop():
			while True:
				try:
					await self._cleanup_expired_sessions()
					# Check every 2 minutes
					await asyncio.sleep(120)
				except Exception as e:
					logger.error(f'Error in cleanup task: {e}')
					await asyncio.sleep(120)

		self._cleanup_task = create_task_with_error_handling(cleanup_loop(), name='mcp_cleanup_loop', suppress_exceptions=True)

	async def run(self):
		"""Run the MCP server."""
		# Start the cleanup task
		await self._start_cleanup_task()

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


async def main(session_timeout_minutes: int = 10):
	if not MCP_AVAILABLE:
		print('MCP SDK is required. Install with: pip install mcp', file=sys.stderr)
		sys.exit(1)

	server = BrowserUseServer(session_timeout_minutes=session_timeout_minutes)
	server._telemetry.capture(
		MCPServerTelemetryEvent(
			version=get_browser_use_version(),
			action='start',
			parent_process_cmdline=get_parent_process_cmdline(),
		)
	)

	try:
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
	asyncio.run(main())
