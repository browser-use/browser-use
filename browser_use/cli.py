# pyright: reportMissingImports=false

# Check for MCP mode early to prevent logging initialization
import sys

if '--mcp' in sys.argv:
	import logging
	import os

	os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'critical'
	os.environ['BROWSER_USE_SETUP_LOGGING'] = 'false'
	logging.disable(logging.CRITICAL)

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.openai.chat import ChatOpenAI

load_dotenv()

from browser_use import Agent, Controller
from browser_use.agent.views import AgentSettings
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.logging_config import addLoggingLevel
from browser_use.telemetry import CLITelemetryEvent, ProductTelemetry
from browser_use.utils import get_browser_use_version

try:
	import click
	from textual import events
	from textual.app import App, ComposeResult
	from textual.binding import Binding
	from textual.containers import Container, HorizontalGroup, VerticalScroll
	from textual.widgets import Footer, Header, Input, Label, Link, RichLog, Static
except ImportError:
	print('⚠️ CLI addon is not installed. Please install it with: `pip install "browser-use[cli]"` and try again.')
	sys.exit(1)


try:
	import readline

	READLINE_AVAILABLE = True
except ImportError:
	# readline not available on Windows by default
	READLINE_AVAILABLE = False


os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'result'

from browser_use.config import CONFIG

# Set USER_DATA_DIR now that CONFIG is imported
USER_DATA_DIR = CONFIG.BROWSER_USE_PROFILES_DIR / 'cli'

# Ensure directories exist
CONFIG.BROWSER_USE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Default User settings
MAX_HISTORY_LENGTH = 100

# Directory setup will happen in functions that need CONFIG


# Logo components with styling for rich panels
BROWSER_LOGO = """
				   [white]   ++++++   +++++++++   [/]                                
				   [white] +++     +++++     +++  [/]                                
				   [white] ++    ++++   ++    ++  [/]                                
				   [white] ++  +++       +++  ++  [/]                                
				   [white]   ++++          +++    [/]                                
				   [white]  +++             +++   [/]                                
				   [white] +++               +++  [/]                                
				   [white] ++   +++      +++  ++  [/]                                
				   [white] ++    ++++   ++    ++  [/]                                
				   [white] +++     ++++++    +++  [/]                                
				   [white]   ++++++    +++++++    [/]                                

[white]██████╗ ██████╗  ██████╗ ██╗    ██╗███████╗███████╗██████╗[/]     [darkorange]██╗   ██╗███████╗███████╗[/]
[white]██╔══██╗██╔══██╗██╔═══██╗██║    ██║██╔════╝██╔════╝██╔══██╗[/]    [darkorange]██║   ██║██╔════╝██╔════╝[/]
[white]██████╔╝██████╔╝██║   ██║██║ █╗ ██║███████╗█████╗  ██████╔╝[/]    [darkorange]██║   ██║███████╗█████╗[/]  
[white]██╔══██╗██╔══██╗██║   ██║██║███╗██║╚════██║██╔══╝  ██╔══██╗[/]    [darkorange]██║   ██║╚════██║██╔══╝[/]  
[white]██████╔╝██║  ██║╚██████╔╝╚███╔███╔╝███████║███████╗██║  ██║[/]    [darkorange]╚██████╔╝███████║███████╗[/]
[white]╚═════╝ ╚═╝  ╚═╝ ╚═════╝  ╚══╝╚══╝ ╚══════╝╚══════╝╚═╝  ╚═╝[/]     [darkorange]╚═════╝ ╚══════╝╚══════╝[/]
"""


# Common UI constants
TEXTUAL_BORDER_STYLES = {'logo': 'blue', 'info': 'blue', 'input': 'orange3', 'working': 'yellow', 'completion': 'green'}


def get_default_config() -> dict[str, Any]:
	"""Return default configuration dictionary using the new config system."""
	# Load config from the new config system
	config_data = CONFIG.load_config()

	# Extract browser profile, llm, and agent configs
	browser_profile = config_data.get('browser_profile', {})
	llm_config = config_data.get('llm', {})
	agent_config = config_data.get('agent', {})

	return {
		'model': {
			'name': llm_config.get('model'),
			'temperature': llm_config.get('temperature', 0.0),
			'api_keys': {
				'OPENAI_API_KEY': llm_config.get('api_key', CONFIG.OPENAI_API_KEY),
				'ANTHROPIC_API_KEY': CONFIG.ANTHROPIC_API_KEY,
				'GOOGLE_API_KEY': CONFIG.GOOGLE_API_KEY,
				'DEEPSEEK_API_KEY': CONFIG.DEEPSEEK_API_KEY,
				'GROK_API_KEY': CONFIG.GROK_API_KEY,
			},
		},
		'agent': agent_config,
		'browser': {
			'headless': browser_profile.get('headless', True),
			'keep_alive': browser_profile.get('keep_alive', True),
			'ignore_https_errors': browser_profile.get('ignore_https_errors', False),
			'user_data_dir': browser_profile.get('user_data_dir'),
			'allowed_domains': browser_profile.get('allowed_domains'),
			'wait_between_actions': browser_profile.get('wait_between_actions'),
			'is_mobile': browser_profile.get('is_mobile'),
			'device_scale_factor': browser_profile.get('device_scale_factor'),
			'disable_security': browser_profile.get('disable_security'),
		},
		'command_history': [],
	}


def load_user_config() -> dict[str, Any]:
	"""Load user configuration using the new config system."""
	# Just get the default config which already loads from the new system
	config = get_default_config()

	# Load command history from a separate file if it exists
	history_file = CONFIG.BROWSER_USE_CONFIG_DIR / 'command_history.json'
	if history_file.exists():
		try:
			with open(history_file) as f:
				config['command_history'] = json.load(f)
		except (FileNotFoundError, json.JSONDecodeError):
			config['command_history'] = []

	return config


def save_user_config(config: dict[str, Any]) -> None:
	"""Save command history only (config is saved via the new system)."""
	# Only save command history to a separate file
	if 'command_history' in config and isinstance(config['command_history'], list):
		# Ensure command history doesn't exceed maximum length
		history = config['command_history']
		if len(history) > MAX_HISTORY_LENGTH:
			history = history[-MAX_HISTORY_LENGTH:]

		# Save to separate history file
		history_file = CONFIG.BROWSER_USE_CONFIG_DIR / 'command_history.json'
		with open(history_file, 'w') as f:
			json.dump(history, f, indent=2)


def update_config_with_click_args(config: dict[str, Any], ctx: click.Context) -> dict[str, Any]:
	"""Update configuration with command-line arguments."""
	# Ensure required sections exist
	if 'model' not in config:
		config['model'] = {}
	if 'browser' not in config:
		config['browser'] = {}

	# Update configuration with command-line args if provided
	if ctx.params.get('model'):
		config['model']['name'] = ctx.params['model']
	if ctx.params.get('headless') is not None:
		config['browser']['headless'] = ctx.params['headless']
	if ctx.params.get('window_width'):
		config['browser']['window_width'] = ctx.params['window_width']
	if ctx.params.get('window_height'):
		config['browser']['window_height'] = ctx.params['window_height']
	if ctx.params.get('user_data_dir'):
		config['browser']['user_data_dir'] = ctx.params['user_data_dir']
	if ctx.params.get('profile_directory'):
		config['browser']['profile_directory'] = ctx.params['profile_directory']
	if ctx.params.get('cdp_url'):
		config['browser']['cdp_url'] = ctx.params['cdp_url']

	# Consolidated proxy dict
	proxy: dict[str, str] = {}
	if ctx.params.get('proxy_url'):
		proxy['server'] = ctx.params['proxy_url']
	if ctx.params.get('no_proxy'):
		# Store as comma-separated list string to match Chrome flag
		proxy['bypass'] = ','.join([p.strip() for p in ctx.params['no_proxy'].split(',') if p.strip()])
	if ctx.params.get('proxy_username'):
		proxy['username'] = ctx.params['proxy_username']
	if ctx.params.get('proxy_password'):
		proxy['password'] = ctx.params['proxy_password']
	if proxy:
		config['browser']['proxy'] = proxy

	return config


def setup_readline_history(history: list[str]) -> None:
	"""Set up readline with command history."""
	if not READLINE_AVAILABLE:
		return

	# Add history items to readline
	for item in history:
		readline.add_history(item)


def get_llm(config: dict[str, Any]):
	"""Get the language model based on config and available API keys."""
	model_config = config.get('model', {})
	model_name = model_config.get('name')
	temperature = model_config.get('temperature', 0.0)

	# Get API key from config or environment
	api_key = model_config.get('api_keys', {}).get('OPENAI_API_KEY') or CONFIG.OPENAI_API_KEY

	if model_name:
		if model_name.startswith('gpt'):
			if not api_key and not CONFIG.OPENAI_API_KEY:
				print('⚠️  OpenAI API key not found. Please update your config or set OPENAI_API_KEY environment variable.')
				sys.exit(1)
			return ChatOpenAI(model=model_name, temperature=temperature, api_key=api_key or CONFIG.OPENAI_API_KEY)
		elif model_name.startswith('claude'):
			if not CONFIG.ANTHROPIC_API_KEY:
				print('⚠️  Anthropic API key not found. Please update your config or set ANTHROPIC_API_KEY environment variable.')
				sys.exit(1)
			return ChatAnthropic(model=model_name, temperature=temperature)
		elif model_name.startswith('gemini'):
			if not CONFIG.GOOGLE_API_KEY:
				print('⚠️  Google API key not found. Please update your config or set GOOGLE_API_KEY environment variable.')
				sys.exit(1)
			return ChatGoogle(model=model_name, temperature=temperature)
		elif model_name.startswith('oci'):
			# OCI models require additional configuration
			print(
				'⚠️  OCI models require manual configuration. Please use the ChatOCIRaw class directly with your OCI credentials.'
			)
			sys.exit(1)

	# Auto-detect based on available API keys
	if api_key or CONFIG.OPENAI_API_KEY:
		return ChatOpenAI(model='gpt-5-mini', temperature=temperature, api_key=api_key or CONFIG.OPENAI_API_KEY)
	elif CONFIG.ANTHROPIC_API_KEY:
		return ChatAnthropic(model='claude-4-sonnet', temperature=temperature)
	elif CONFIG.GOOGLE_API_KEY:
		return ChatGoogle(model='gemini-2.5-pro', temperature=temperature)
	else:
		print(
			'⚠️  No API keys found. Please update your config or set one of: OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY.'
		)
		sys.exit(1)


class RichLogHandler(logging.Handler):
	"""Custom logging handler that redirects logs to a RichLog widget."""

	def __init__(self, rich_log: RichLog):
		super().__init__()
		self.rich_log = rich_log

	def emit(self, record):
		try:
			msg = self.format(record)
			self.rich_log.write(msg)
		except Exception:
			self.handleError(record)


class BrowserUseApp(App):
	"""Browser-use TUI application."""

	# Make it an inline app instead of fullscreen
	# MODES = {"light"}  # Ensure app is inline, not fullscreen

	CSS = """
	#main-container {
		height: 100%;
		layout: vertical;
	}
	
	#logo-panel, #links-panel, #paths-panel, #info-panels {
		border: solid $primary;
		margin: 0 0 0 0; 
		padding: 0;
	}
	
	#info-panels {
		display: none;
		layout: vertical;
		height: auto;
		min-height: 5;
		margin: 0 0 1 0;
	}
	
	#top-panels {
		layout: horizontal;
		height: auto;
		width: 100%;
	}
	
	#browser-panel, #model-panel {
		width: 1fr;
		height: 100%;
		padding: 1;
		border-right: solid $primary;
	}
	
	#model-panel {
		border-right: none;
	}
	
	#tasks-panel {
		height: auto;
		max-height: 10;
		overflow-y: scroll;
		padding: 1;
		border-top: solid $primary;
	}
	
	#browser-info, #model-info, #tasks-info {
		height: auto;
		margin: 0;
		padding: 0;
		background: transparent;
		overflow-y: auto;
		min-height: 3;
	}
	
	#three-column-container {
		height: 1fr;
		layout: horizontal;
		width: 100%;
		display: none;
	}
	
	#main-output-column {
		width: 1fr;
		height: 100%;
		border: solid $primary;
		padding: 0;
		margin: 0 1 0 0;
	}
	
	#events-column {
		width: 1fr;
		height: 100%;
		border: solid $warning;
		padding: 0;
		margin: 0 1 0 0;
	}
	
	#cdp-column {
		width: 1fr;
		height: 100%;
		border: solid $accent;
		padding: 0;
		margin: 0;
	}
	
	#main-output-log, #events-log, #cdp-log {
		height: 100%;
		overflow-y: scroll;
		background: $surface;
		color: $text;
		width: 100%;
		padding: 1;
	}
	
	#events-log {
		color: $warning;
	}
	
	#cdp-log {
		color: $accent-lighten-2;
	}
	
	#logo-panel {
		width: 100%;
		height: auto;
		content-align: center middle;
		text-align: center;
	}
	
	#links-panel {
		width: 100%;
		padding: 1;
		border: solid $primary;
		height: auto;
	}
	
	.link-white {
		color: white;
	}
	
	.link-purple {
		color: purple;
	}
	
	.link-magenta {
		color: magenta;
	}
	
	.link-green {
		color: green;
	}

	HorizontalGroup {
		height: auto;
	}
	
	.link-label {
		width: auto;
	}
	
	.link-url {
		width: auto;
	}
	
	.link-row {
		width: 100%;
		height: auto;
	}
	
	#paths-panel {
		color: $text-muted;
	}
	
	#task-input-container {
		border: solid $accent;
		padding: 1;
		margin-bottom: 1;
		height: auto;
		dock: bottom;
	}
	
	#task-label {
		color: $accent;
		padding-bottom: 1;
	}
	
	#task-input {
		width: 100%;
	}
	"""

	BINDINGS = [
		Binding('ctrl+c', 'quit', 'Quit', priority=True, show=True),
		Binding('ctrl+q', 'quit', 'Quit', priority=True),
		Binding('ctrl+d', 'quit', 'Quit', priority=True),
		Binding('up', 'input_history_prev', 'Previous command', show=False),
		Binding('down', 'input_history_next', 'Next command', show=False),
	]

	def __init__(self, config: dict[str, Any], *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.config = config
		self.browser_session: BrowserSession | None = None  # Will be set before app.run_async()
		self.controller: Controller | None = None  # Will be set before app.run_async()
		self.agent: Agent | None = None
		self.llm: Any | None = None  # Will be set before app.run_async()
		self.task_history = config.get('command_history', [])
		# Track current position in history for up/down navigation
		self.history_index = len(self.task_history)
		# Initialize telemetry
		self._telemetry = ProductTelemetry()
		# Store for event bus handler
		self._event_bus_handler_id = None
		self._event_bus_handler_func = None
		# Timer for info panel updates
		self._info_panel_timer = None

	def setup_richlog_logging(self) -> None:
		"""Set up logging to redirect to RichLog widget instead of stdout."""
		# Try to add RESULT level if it doesn't exist
		try:
			addLoggingLevel('RESULT', 35)
		except AttributeError:
			pass  # Level already exists, which is fine

		# Get the main output RichLog widget
		rich_log = self.query_one('#main-output-log', RichLog)

		# Create and set up the custom handler
		log_handler = RichLogHandler(rich_log)
		log_type = os.getenv('BROWSER_USE_LOGGING_LEVEL', 'result').lower()

		class BrowserUseFormatter(logging.Formatter):
			def format(self, record):
				# if isinstance(record.name, str) and record.name.startswith('browser_use.'):
				# 	record.name = record.name.split('.')[-2]
				return super().format(record)

		# Set up the formatter based on log type
		if log_type == 'result':
			log_handler.setLevel('RESULT')
			log_handler.setFormatter(BrowserUseFormatter('%(message)s'))
		else:
			log_handler.setFormatter(BrowserUseFormatter('%(levelname)-8s [%(name)s] %(message)s'))

		# Configure root logger - Replace ALL handlers, not just stdout handlers
		root = logging.getLogger()

		# Clear all existing handlers to prevent output to stdout/stderr
		root.handlers = []
		root.addHandler(log_handler)

		# Set log level based on environment variable
		if log_type == 'result':
			root.setLevel('RESULT')
		elif log_type == 'debug':
			root.setLevel(logging.DEBUG)
		else:
			root.setLevel(logging.INFO)

		# Configure browser_use logger and all its sub-loggers
		browser_use_logger = logging.getLogger('browser_use')
		browser_use_logger.propagate = False  # Don't propagate to root logger
		browser_use_logger.handlers = [log_handler]  # Replace any existing handlers
		browser_use_logger.setLevel(root.level)

		# Also ensure agent loggers go to the main output
		# Use a wildcard pattern to catch all agent-related loggers
		for logger_name in ['browser_use.Agent', 'browser_use.controller', 'browser_use.agent', 'browser_use.agent.service']:
			agent_logger = logging.getLogger(logger_name)
			agent_logger.propagate = False
			agent_logger.handlers = [log_handler]
			agent_logger.setLevel(root.level)

		# Also catch any dynamically created agent loggers with task IDs
		for name, logger in logging.Logger.manager.loggerDict.items():
			if isinstance(name, str) and 'browser_use.Agent' in name:
				if isinstance(logger, logging.Logger):
					logger.propagate = False
					logger.handlers = [log_handler]
					logger.setLevel(root.level)

		# Silence third-party loggers but keep them using our handler
		for logger_name in [
			'WDM',
			'httpx',
			'selenium',
			'playwright',
			'urllib3',
			'asyncio',
			'openai',
			'httpcore',
			'charset_normalizer',
			'anthropic._base_client',
			'PIL.PngImagePlugin',
			'trafilatura.htmlprocessing',
			'trafilatura',
			'groq',
			'portalocker',
			'portalocker.utils',
		]:
			third_party = logging.getLogger(logger_name)
			third_party.setLevel(logging.ERROR)
			third_party.propagate = False
			third_party.handlers = [log_handler]  # Use our handler to prevent stdout/stderr leakage

	def on_mount(self) -> None:
		"""Set up components when app is mounted."""
		# We'll use a file logger since stdout is now controlled by Textual
		logger = logging.getLogger('browser_use.on_mount')
		logger.debug('on_mount() method started')

		# Step 1: Set up custom logging to RichLog
		logger.debug('Setting up RichLog logging...')
		try:
			self.setup_richlog_logging()
			logger.debug('RichLog logging set up successfully')
		except Exception as e:
			logger.error(f'Error setting up RichLog logging: {str(e)}', exc_info=True)
			raise RuntimeError(f'Failed to set up RichLog logging: {str(e)}')

		# Step 2: Set up input history
		logger.debug('Setting up readline history...')
		try:
			if READLINE_AVAILABLE and self.task_history:
				for item in self.task_history:
					readline.add_history(item)
				logger.debug(f'Added {len(self.task_history)} items to readline history')
			else:
				logger.debug('No readline history to set up')
		except Exception as e:
			logger.error(f'Error setting up readline history: {str(e)}', exc_info=False)
			# Non-critical, continue

		# Step 3: Focus the input field
		logger.debug('Focusing input field...')
		try:
			input_field = self.query_one('#task-input', Input)
			input_field.focus()
			logger.debug('Input field focused')
		except Exception as e:
			logger.error(f'Error focusing input field: {str(e)}', exc_info=True)
			# Non-critical, continue

		# Step 5: Setup CDP logger and event bus listener if browser session is available
		logger.debug('Setting up CDP logging and event bus listener...')
		try:
			self.setup_cdp_logger()
			if self.browser_session:
				self.setup_event_bus_listener()
			logger.debug('CDP logging and event bus setup complete')
		except Exception as e:
			logger.error(f'Error setting up CDP logging/event bus: {str(e)}', exc_info=True)
			# Non-critical, continue

		# Capture telemetry for CLI start
		self._telemetry.capture(
			CLITelemetryEvent(
				version=get_browser_use_version(),
				action='start',
				mode='interactive',
				model=self.llm.model if self.llm and hasattr(self.llm, 'model') else None,
				model_provider=self.llm.provider if self.llm and hasattr(self.llm, 'provider') else None,
			)
		)

		logger.debug('on_mount() completed successfully')

	def on_input_key_up(self, event: events.Key) -> None:
		"""Handle up arrow key in the input field."""
		# For textual key events, we need to check focus manually
		input_field = self.query_one('#task-input', Input)
		if not input_field.has_focus:
			return

		# Only process if we have history
		if not self.task_history:
			return

		# Move back in history if possible
		if self.history_index > 0:
			self.history_index -= 1
			task_input = self.query_one('#task-input', Input)
			task_input.value = self.task_history[self.history_index]
			# Move cursor to end of text
			task_input.cursor_position = len(task_input.value)

		# Prevent default behavior (cursor movement)
		event.prevent_default()
		event.stop()

	def on_input_key_down(self, event: events.Key) -> None:
		"""Handle down arrow key in the input field."""
		# For textual key events, we need to check focus manually
		input_field = self.query_one('#task-input', Input)
		if not input_field.has_focus:
			return

		# Only process if we have history
		if not self.task_history:
			return

		# Move forward in history or clear input if at the end
		if self.history_index < len(self.task_history) - 1:
			self.history_index += 1
			task_input = self.query_one('#task-input', Input)
			task_input.value = self.task_history[self.history_index]
			# Move cursor to end of text
			task_input.cursor_position = len(task_input.value)
		elif self.history_index == len(self.task_history) - 1:
			# At the end of history, go to "new line" state
			self.history_index += 1
			self.query_one('#task-input', Input).value = ''

		# Prevent default behavior (cursor movement)
		event.prevent_default()
		event.stop()

	async def on_key(self, event: events.Key) -> None:
		"""Handle key events at the app level to ensure graceful exit."""
		# Handle Ctrl+C, Ctrl+D, and Ctrl+Q for app exit
		if event.key == 'ctrl+c' or event.key == 'ctrl+d' or event.key == 'ctrl+q':
			await self.action_quit()
			event.stop()
			event.prevent_default()

	def on_input_submitted(self, event: Input.Submitted) -> None:
		"""Handle task input submission."""
		if event.input.id == 'task-input':
			task = event.input.value
			if not task.strip():
				return

			# Add to history if it's new
			if task.strip() and (not self.task_history or task != self.task_history[-1]):
				self.task_history.append(task)
				self.config['command_history'] = self.task_history
				save_user_config(self.config)

			# Reset history index to point past the end of history
			self.history_index = len(self.task_history)

			# Hide logo, links, and paths panels
			self.hide_intro_panels()

			# Process the task
			self.run_task(task)

			# Clear the input
			event.input.value = ''

	def hide_intro_panels(self) -> None:
		"""Hide the intro panels, show info panels and the three-column view."""
		try:
			# Get the panels
			logo_panel = self.query_one('#logo-panel')
			links_panel = self.query_one('#links-panel')
			paths_panel = self.query_one('#paths-panel')
			info_panels = self.query_one('#info-panels')
			three_column = self.query_one('#three-column-container')

			# Hide intro panels if they're visible and show info panels + three-column view
			if logo_panel.display:
				logging.debug('Hiding intro panels and showing info panels + three-column view')

				logo_panel.display = False
				links_panel.display = False
				paths_panel.display = False

				# Show info panels and three-column container
				info_panels.display = True
				three_column.display = True

				# Start updating info panels
				self.update_info_panels()

				logging.debug('Info panels and three-column view should now be visible')
		except Exception as e:
			logging.error(f'Error in hide_intro_panels: {str(e)}')

	def setup_event_bus_listener(self) -> None:
		"""Setup listener for browser session event bus."""
		if not self.browser_session or not self.browser_session.event_bus:
			return

		# Clean up any existing handler before registering a new one
		if self._event_bus_handler_func is not None:
			try:
				# Remove handler from the event bus's internal handlers dict
				if hasattr(self.browser_session.event_bus, 'handlers'):
					# Find and remove our handler function from all event patterns
					for event_type, handler_list in list(self.browser_session.event_bus.handlers.items()):
						# Remove our specific handler function object
						if self._event_bus_handler_func in handler_list:
							handler_list.remove(self._event_bus_handler_func)
							logging.debug(f'Removed old handler from event type: {event_type}')
			except Exception as e:
				logging.debug(f'Error cleaning up event bus handler: {e}')
			self._event_bus_handler_func = None
			self._event_bus_handler_id = None

		try:
			# Get the events log widget
			events_log = self.query_one('#events-log', RichLog)
		except Exception:
			# Widget not ready yet
			return

		# Create handler to log all events
		def log_event(event):
			event_name = event.__class__.__name__
			# Format event data nicely
			try:
				if hasattr(event, 'model_dump'):
					event_data = event.model_dump(exclude_unset=True)
					# Remove large fields
					if 'screenshot' in event_data:
						event_data['screenshot'] = '<bytes>'
					if 'dom_state' in event_data:
						event_data['dom_state'] = '<truncated>'
					event_str = str(event_data) if event_data else ''
				else:
					event_str = str(event)

				# Truncate long strings
				if len(event_str) > 200:
					event_str = event_str[:200] + '...'

				events_log.write(f'[yellow]→ {event_name}[/] {event_str}')
			except Exception as e:
				events_log.write(f'[red]→ {event_name}[/] (error formatting: {e})')

		# Store the handler function before registering it
		self._event_bus_handler_func = log_event
		self._event_bus_handler_id = id(log_event)

		# Register wildcard handler for all events
		self.browser_session.event_bus.on('*', log_event)
		logging.debug(f'Registered new event bus handler with id: {self._event_bus_handler_id}')

	def setup_cdp_logger(self) -> None:
		"""Setup CDP message logger to capture already-transformed CDP logs."""
		# No need to configure levels - setup_logging() already handles that
		# We just need to capture the transformed logs and route them to the CDP pane

		# Get the CDP log widget
		cdp_log = self.query_one('#cdp-log', RichLog)

		# Create custom handler for CDP logging
		class CDPLogHandler(logging.Handler):
			def __init__(self, rich_log: RichLog):
				super().__init__()
				self.rich_log = rich_log

			def emit(self, record):
				try:
					msg = self.format(record)
					# Truncate very long messages
					if len(msg) > 300:
						msg = msg[:300] + '...'
					# Color code by level
					if record.levelno >= logging.ERROR:
						self.rich_log.write(f'[red]{msg}[/]')
					elif record.levelno >= logging.WARNING:
						self.rich_log.write(f'[yellow]{msg}[/]')
					else:
						self.rich_log.write(f'[cyan]{msg}[/]')
				except Exception:
					self.handleError(record)

		# Setup handler for cdp_use loggers
		cdp_handler = CDPLogHandler(cdp_log)
		cdp_handler.setFormatter(logging.Formatter('%(message)s'))
		cdp_handler.setLevel(logging.DEBUG)

		# Route CDP logs to the CDP pane
		# These are already transformed by cdp_use and at the right level from setup_logging
		for logger_name in ['websockets.client', 'cdp_use', 'cdp_use.client', 'cdp_use.cdp', 'cdp_use.cdp.registry']:
			logger = logging.getLogger(logger_name)
			# Add our handler (don't replace - keep existing console handler too)
			if cdp_handler not in logger.handlers:
				logger.addHandler(cdp_handler)

	def scroll_to_input(self) -> None:
		"""Scroll to the input field to ensure it's visible."""
		input_container = self.query_one('#task-input-container')
		input_container.scroll_visible()

	def run_task(self, task: str) -> None:
		"""Launch the task in a background worker."""
		# Create or update the agent
		agent_settings = AgentSettings.model_validate(self.config.get('agent', {}))

		# Get the logger
		logger = logging.getLogger('browser_use.app')

		# Make sure intro is hidden and log is ready
		self.hide_intro_panels()

		# Clear the main output log to start fresh
		rich_log = self.query_one('#main-output-log', RichLog)
		rich_log.clear()

		if self.agent is None:
			if not self.llm:
				raise RuntimeError('LLM not initialized')
			self.agent = Agent(
				task=task,
				llm=self.llm,
				controller=self.controller if self.controller else Controller(),
				browser_session=self.browser_session,
				source='cli',
				**agent_settings.model_dump(),
			)
			# Update our browser_session reference to point to the agent's
			if hasattr(self.agent, 'browser_session'):
				self.browser_session = self.agent.browser_session
				# Set up event bus listener (will clean up any old handler first)
				self.setup_event_bus_listener()
		else:
			self.agent.add_new_task(task)

		# Let the agent run in the background
		async def agent_task_worker() -> None:
			logger.debug('\n🚀 Working on task: %s', task)

			# Set flags to indicate the agent is running
			if self.agent:
				self.agent.running = True  # type: ignore
				self.agent.last_response_time = 0  # type: ignore

			# Panel updates are already happening via the timer in update_info_panels

			task_start_time = time.time()
			error_msg = None

			try:
				# Capture telemetry for message sent
				self._telemetry.capture(
					CLITelemetryEvent(
						version=get_browser_use_version(),
						action='message_sent',
						mode='interactive',
						model=self.llm.model if self.llm and hasattr(self.llm, 'model') else None,
						model_provider=self.llm.provider if self.llm and hasattr(self.llm, 'provider') else None,
					)
				)

				# Run the agent task, redirecting output to RichLog through our handler
				if self.agent:
					await self.agent.run()
			except Exception as e:
				error_msg = str(e)
				logger.error('\nError running agent: %s', str(e))
			finally:
				# Clear the running flag
				if self.agent:
					self.agent.running = False  # type: ignore

				# Capture telemetry for task completion
				duration = time.time() - task_start_time
				self._telemetry.capture(
					CLITelemetryEvent(
						version=get_browser_use_version(),
						action='task_completed' if error_msg is None else 'error',
						mode='interactive',
						model=self.llm.model if self.llm and hasattr(self.llm, 'model') else None,
						model_provider=self.llm.provider if self.llm and hasattr(self.llm, 'provider') else None,
						duration_seconds=duration,
						error_message=error_msg,
					)
				)

				logger.debug('\n✅ Task completed!')

				# Make sure the task input container is visible
				task_input_container = self.query_one('#task-input-container')
				task_input_container.display = True

				# Refocus the input field
				input_field = self.query_one('#task-input', Input)
				input_field.focus()

				# Ensure the input is visible by scrolling to it
				self.call_after_refresh(self.scroll_to_input)

		# Run the worker
		self.run_worker(agent_task_worker, name='agent_task')

	def action_input_history_prev(self) -> None:
		"""Navigate to the previous item in command history."""
		# Only process if we have history and input is focused
		input_field = self.query_one('#task-input', Input)
		if not input_field.has_focus or not self.task_history:
			return

		# Move back in history if possible
		if self.history_index > 0:
			self.history_index -= 1
			input_field.value = self.task_history[self.history_index]
			# Move cursor to end of text
			input_field.cursor_position = len(input_field.value)

	def action_input_history_next(self) -> None:
		"""Navigate to the next item in command history or clear input."""
		# Only process if we have history and input is focused
		input_field = self.query_one('#task-input', Input)
		if not input_field.has_focus or not self.task_history:
			return

		# Move forward in history or clear input if at the end
		if self.history_index < len(self.task_history) - 1:
			self.history_index += 1
			input_field.value = self.task_history[self.history_index]
			# Move cursor to end of text
			input_field.cursor_position = len(input_field.value)
		elif self.history_index == len(self.task_history) - 1:
			# At the end of history, go to "new line" state
			self.history_index += 1
			input_field.value = ''

	async def action_quit(self) -> None:
		"""Quit the application and clean up resources."""
		# Note: We don't need to close the browser session here because:
		# 1. If an agent exists, it already called browser_session.stop() in its run() method
		# 2. If keep_alive=True (default), we want to leave the browser running anyway
		# This prevents the duplicate "stop() called" messages in the logs

		# Flush telemetry before exiting
		self._telemetry.flush()

		# Exit the application
		self.exit()
		print('\nTry running tasks on our cloud: https://browser-use.com')

	def compose(self) -> ComposeResult:
		"""Create the UI layout."""
		yield Header()

		# Main container for app content
		with Container(id='main-container'):
			# Logo panel
			yield Static(BROWSER_LOGO, id='logo-panel', markup=True)

			# Links panel with URLs
			with Container(id='links-panel'):
				with HorizontalGroup(classes='link-row'):
					yield Static('Run at scale on cloud:    [blink]☁️[/]  ', markup=True, classes='link-label')
					yield Link('https://browser-use.com', url='https://browser-use.com', classes='link-white link-url')

				yield Static('')  # Empty line

				with HorizontalGroup(classes='link-row'):
					yield Static('Chat & share on Discord:  🚀 ', markup=True, classes='link-label')
					yield Link(
						'https://discord.gg/ESAUZAdxXY', url='https://discord.gg/ESAUZAdxXY', classes='link-purple link-url'
					)

				with HorizontalGroup(classes='link-row'):
					yield Static('Get prompt inspiration:   🦸 ', markup=True, classes='link-label')
					yield Link(
						'https://github.com/browser-use/awesome-prompts',
						url='https://github.com/browser-use/awesome-prompts',
						classes='link-magenta link-url',
					)

				with HorizontalGroup(classes='link-row'):
					yield Static('[dim]Report any issues:[/]        🐛 ', markup=True, classes='link-label')
					yield Link(
						'https://github.com/browser-use/browser-use/issues',
						url='https://github.com/browser-use/browser-use/issues',
						classes='link-green link-url',
					)

			# Paths panel
			yield Static(
				f' ⚙️  Settings saved to:              {str(CONFIG.BROWSER_USE_CONFIG_FILE.resolve()).replace(str(Path.home()), "~")}\n'
				f' 📁 Outputs & recordings saved to:  {str(Path(".").resolve()).replace(str(Path.home()), "~")}',
				id='paths-panel',
				markup=True,
			)

			# Info panels (hidden by default, shown when task starts)
			with Container(id='info-panels'):
				# Top row with browser and model panels side by side
				with Container(id='top-panels'):
					# Browser panel
					with Container(id='browser-panel'):
						yield RichLog(id='browser-info', markup=True, highlight=True, wrap=True)

					# Model panel
					with Container(id='model-panel'):
						yield RichLog(id='model-info', markup=True, highlight=True, wrap=True)

				# Tasks panel (full width, below browser and model)
				with VerticalScroll(id='tasks-panel'):
					yield RichLog(id='tasks-info', markup=True, highlight=True, wrap=True, auto_scroll=True)

			# Three-column container (hidden by default)
			with Container(id='three-column-container'):
				# Column 1: Main output
				with VerticalScroll(id='main-output-column'):
					yield RichLog(highlight=True, markup=True, id='main-output-log', wrap=True, auto_scroll=True)

				# Column 2: Event bus events
				with VerticalScroll(id='events-column'):
					yield RichLog(highlight=True, markup=True, id='events-log', wrap=True, auto_scroll=True)

				# Column 3: CDP messages
				with VerticalScroll(id='cdp-column'):
					yield RichLog(highlight=True, markup=True, id='cdp-log', wrap=True, auto_scroll=True)

			# Task input container (now at the bottom)
			with Container(id='task-input-container'):
				yield Label('🔍 What would you like me to do on the web?', id='task-label')
				yield Input(placeholder='Enter your task...', id='task-input')

		yield Footer()

	def update_info_panels(self) -> None:
		"""Update all information panels with current state."""
		try:
			# Update actual content
			self.update_browser_panel()
			self.update_model_panel()
			self.update_tasks_panel()
		except Exception as e:
			logging.error(f'Error in update_info_panels: {str(e)}')
		finally:
			# Always schedule the next update - will update at 1-second intervals
			# This ensures continuous updates even if agent state changes
			self.set_timer(1.0, self.update_info_panels)

	def update_browser_panel(self) -> None:
		"""Update browser information panel with details about the browser."""
		browser_info = self.query_one('#browser-info', RichLog)
		browser_info.clear()

		# Try to use the agent's browser session if available
		browser_session = self.browser_session
		if hasattr(self, 'agent') and self.agent and hasattr(self.agent, 'browser_session'):
			browser_session = self.agent.browser_session

		if browser_session:
			try:
				# Check if browser session has a CDP client
				if not hasattr(browser_session, 'cdp_client') or browser_session.cdp_client is None:
					browser_info.write('[yellow]Browser session created, waiting for browser to launch...[/]')
					return

				# Update our reference if we're using the agent's session
				if browser_session != self.browser_session:
					self.browser_session = browser_session

				# Get basic browser info from browser_profile
				browser_type = 'Chromium'
				headless = browser_session.browser_profile.headless

				# Determine connection type based on config
				connection_type = 'playwright'  # Default
				if browser_session.cdp_url:
					connection_type = 'CDP'
				elif browser_session.browser_profile.executable_path:
					connection_type = 'user-provided'

				# Get window size details from browser_profile
				window_width = None
				window_height = None
				if browser_session.browser_profile.viewport:
					window_width = browser_session.browser_profile.viewport.width
					window_height = browser_session.browser_profile.viewport.height

				# Try to get browser PID
				browser_pid = 'Unknown'
				connected = False
				browser_status = '[red]Disconnected[/]'

				try:
					# Check if browser PID is available
					# Check if we have a CDP client
					if browser_session.cdp_client is not None:
						connected = True
						browser_status = '[green]Connected[/]'
						browser_pid = 'N/A'
				except Exception as e:
					browser_pid = f'Error: {str(e)}'

				# Display browser information
				browser_info.write(f'[bold cyan]Chromium[/] Browser ({browser_status})')
				browser_info.write(
					f'Type: [yellow]{connection_type}[/] [{"green" if not headless else "red"}]{" (headless)" if headless else ""}[/]'
				)
				browser_info.write(f'PID: [dim]{browser_pid}[/]')
				browser_info.write(f'CDP Port: {browser_session.cdp_url}')

				if window_width and window_height:
					browser_info.write(f'Window: [blue]{window_width}[/] × [blue]{window_height}[/]')

				# Include additional information about the browser if needed
				if connected and hasattr(self, 'agent') and self.agent:
					try:
						# Show when the browser was connected
						timestamp = int(time.time())
						current_time = time.strftime('%H:%M:%S', time.localtime(timestamp))
						browser_info.write(f'Last updated: [dim]{current_time}[/]')
					except Exception:
						pass

					# Show the agent's current page URL if available
					if browser_session.agent_focus:
						current_url = (
							browser_session.agent_focus.url.replace('https://', '')
							.replace('http://', '')
							.replace('www.', '')[:36]
							+ '…'
						)
						browser_info.write(f'👁️  [green]{current_url}[/]')
			except Exception as e:
				browser_info.write(f'[red]Error updating browser info: {str(e)}[/]')
		else:
			browser_info.write('[red]Browser not initialized[/]')

	def update_model_panel(self) -> None:
		"""Update model information panel with details about the LLM."""
		model_info = self.query_one('#model-info', RichLog)
		model_info.clear()

		if self.llm:
			# Get model details
			model_name = 'Unknown'
			if hasattr(self.llm, 'model_name'):
				model_name = self.llm.model_name
			elif hasattr(self.llm, 'model'):
				model_name = self.llm.model

			# Show model name
			if self.agent:
				temp_str = f'{self.llm.temperature}ºC ' if self.llm.temperature else ''
				vision_str = '+ vision ' if self.agent.settings.use_vision else ''
				model_info.write(
					f'[white]LLM:[/] [blue]{self.llm.__class__.__name__} [yellow]{model_name}[/] {temp_str}{vision_str}'
				)
			else:
				model_info.write(f'[white]LLM:[/] [blue]{self.llm.__class__.__name__} [yellow]{model_name}[/]')

			# Show token usage statistics if agent exists and has history
			if self.agent and hasattr(self.agent, 'state') and hasattr(self.agent.state, 'history'):
				# Calculate tokens per step
				num_steps = len(self.agent.history.history)

				# Get the last step metadata to show the most recent LLM response time
				if num_steps > 0 and self.agent.history.history[-1].metadata:
					last_step = self.agent.history.history[-1]
					if last_step.metadata:
						step_duration = last_step.metadata.duration_seconds
					else:
						step_duration = 0

				# Show total duration
				total_duration = self.agent.history.total_duration_seconds()
				if total_duration > 0:
					model_info.write(f'[white]Total Duration:[/] [magenta]{total_duration:.2f}s[/]')

					# Calculate response time metrics
					model_info.write(f'[white]Last Step Duration:[/] [magenta]{step_duration:.2f}s[/]')

				# Add current state information
				if hasattr(self.agent, 'running'):
					if getattr(self.agent, 'running', False):
						model_info.write('[yellow]LLM is thinking[blink]...[/][/]')
					elif hasattr(self.agent, 'state') and hasattr(self.agent.state, 'paused') and self.agent.state.paused:
						model_info.write('[orange]LLM paused[/]')
		else:
			model_info.write('[red]Model not initialized[/]')

	def update_tasks_panel(self) -> None:
		"""Update tasks information panel with details about the tasks and steps hierarchy."""
		tasks_info = self.query_one('#tasks-info', RichLog)
		tasks_info.clear()

		if self.agent:
			# Check if agent has tasks
			task_history = []
			message_history = []

			# Try to extract tasks by looking at message history
			if hasattr(self.agent, '_message_manager') and self.agent._message_manager:
				message_history = self.agent._message_manager.state.history.get_messages()

				# Extract original task(s)
				original_tasks = []
				for msg in message_history:
					if hasattr(msg, 'content'):
						content = msg.content
						if isinstance(content, str) and 'Your ultimate task is:' in content:
							task_text = content.split('"""')[1].strip()
							original_tasks.append(task_text)

				if original_tasks:
					tasks_info.write('[bold green]TASK:[/]')
					for i, task in enumerate(original_tasks, 1):
						# Only show latest task if multiple task changes occurred
						if i == len(original_tasks):
							tasks_info.write(f'[white]{task}[/]')
					tasks_info.write('')

			# Get current state information
			current_step = self.agent.state.n_steps if hasattr(self.agent, 'state') else 0

			# Get all agent history items
			history_items = []
			if hasattr(self.agent, 'state') and hasattr(self.agent.state, 'history'):
				history_items = self.agent.history.history

				if history_items:
					tasks_info.write('[bold yellow]STEPS:[/]')

					for idx, item in enumerate(history_items, 1):
						# Determine step status
						step_style = '[green]✓[/]'

						# For the current step, show it as in progress
						if idx == current_step:
							step_style = '[yellow]⟳[/]'

						# Check if this step had an error
						if item.result and any(result.error for result in item.result):
							step_style = '[red]✗[/]'

						# Show step number
						tasks_info.write(f'{step_style} Step {idx}/{current_step}')

						# Show goal if available
						if item.model_output and hasattr(item.model_output, 'current_state'):
							# Show goal for this step
							goal = item.model_output.current_state.next_goal
							if goal:
								# Take just the first line for display
								goal_lines = goal.strip().split('\n')
								goal_summary = goal_lines[0]
								tasks_info.write(f'   [cyan]Goal:[/] {goal_summary}')

							# Show evaluation of previous goal (feedback)
							eval_prev = item.model_output.current_state.evaluation_previous_goal
							if eval_prev and idx > 1:  # Only show for steps after the first
								eval_lines = eval_prev.strip().split('\n')
								eval_summary = eval_lines[0]
								eval_summary = eval_summary.replace('Success', '✅ ').replace('Failed', '❌ ').strip()
								tasks_info.write(f'   [tan]Evaluation:[/] {eval_summary}')

						# Show actions taken in this step
						if item.model_output and item.model_output.action:
							tasks_info.write('   [purple]Actions:[/]')
							for action_idx, action in enumerate(item.model_output.action, 1):
								action_type = action.__class__.__name__
								if hasattr(action, 'model_dump'):
									# For proper actions, show the action type
									action_dict = action.model_dump(exclude_unset=True)
									if action_dict:
										action_name = list(action_dict.keys())[0]
										tasks_info.write(f'     {action_idx}. [blue]{action_name}[/]')

						# Show results or errors from this step
						if item.result:
							for result in item.result:
								if result.error:
									error_text = result.error
									tasks_info.write(f'   [red]Error:[/] {error_text}')
								elif result.extracted_content:
									content = result.extracted_content
									tasks_info.write(f'   [green]Result:[/] {content}')

						# Add a space between steps for readability
						tasks_info.write('')

			# If agent is actively running, show a status indicator
			if hasattr(self.agent, 'running') and getattr(self.agent, 'running', False):
				tasks_info.write('[yellow]Agent is actively working[blink]...[/][/]')
			elif hasattr(self.agent, 'state') and hasattr(self.agent.state, 'paused') and self.agent.state.paused:
				tasks_info.write('[orange]Agent is paused (press Enter to resume)[/]')
		else:
			tasks_info.write('[dim]Agent not initialized[/]')

		# Force scroll to bottom
		tasks_panel = self.query_one('#tasks-panel')
		tasks_panel.scroll_end(animate=False)


async def run_prompt_mode(prompt: str, ctx: click.Context, debug: bool = False):
	"""Run browser-use in non-interactive mode with a single prompt."""
	# Import and call setup_logging to ensure proper initialization
	from browser_use.logging_config import setup_logging

	# Set up logging to only show results by default
	os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'result'

	# Re-run setup_logging to apply the new log level
	setup_logging()

	# The logging is now properly configured by setup_logging()
	# No need to manually configure handlers since setup_logging() handles it

	# Initialize telemetry
	telemetry = ProductTelemetry()
	start_time = time.time()
	error_msg = None

	try:
		# Load config
		config = load_user_config()
		config = update_config_with_click_args(config, ctx)

		# Get LLM
		llm = get_llm(config)

		# Capture telemetry for CLI start in oneshot mode
		telemetry.capture(
			CLITelemetryEvent(
				version=get_browser_use_version(),
				action='start',
				mode='oneshot',
				model=llm.model if hasattr(llm, 'model') else None,
				model_provider=llm.__class__.__name__ if llm else None,
			)
		)

		# Get agent settings from config
		agent_settings = AgentSettings.model_validate(config.get('agent', {}))

		# Create browser session with config parameters
		browser_config = config.get('browser', {})
		# Remove None values from browser_config
		browser_config = {k: v for k, v in browser_config.items() if v is not None}
		# Create BrowserProfile with user_data_dir
		profile = BrowserProfile(user_data_dir=str(USER_DATA_DIR), **browser_config)
		browser_session = BrowserSession(
			browser_profile=profile,
		)

		# Create and run agent
		agent = Agent(
			task=prompt,
			llm=llm,
			browser_session=browser_session,
			source='cli',
			**agent_settings.model_dump(),
		)

		await agent.run()

		# Ensure the browser session is fully stopped
		# The agent's close() method only kills the browser if keep_alive=False,
		# but we need to ensure all background tasks are stopped regardless
		if browser_session:
			try:
				# Kill the browser session to stop all background tasks
				await browser_session.kill()
			except Exception:
				# Ignore errors during cleanup
				pass

		# Capture telemetry for successful completion
		telemetry.capture(
			CLITelemetryEvent(
				version=get_browser_use_version(),
				action='task_completed',
				mode='oneshot',
				model=llm.model if hasattr(llm, 'model') else None,
				model_provider=llm.__class__.__name__ if llm else None,
				duration_seconds=time.time() - start_time,
			)
		)

	except Exception as e:
		error_msg = str(e)
		# Capture telemetry for error
		telemetry.capture(
			CLITelemetryEvent(
				version=get_browser_use_version(),
				action='error',
				mode='oneshot',
				model=llm.model if hasattr(llm, 'model') else None,
				model_provider=llm.__class__.__name__ if llm and 'llm' in locals() else None,
				duration_seconds=time.time() - start_time,
				error_message=error_msg,
			)
		)
		if debug:
			import traceback

			traceback.print_exc()
		else:
			print(f'Error: {str(e)}', file=sys.stderr)
		sys.exit(1)
	finally:
		# Ensure telemetry is flushed
		telemetry.flush()

		# Give a brief moment for cleanup to complete
		await asyncio.sleep(0.1)

		# Cancel any remaining tasks to ensure clean exit
		tasks = [t for t in asyncio.all_tasks() if t != asyncio.current_task()]
		for task in tasks:
			task.cancel()

		# Wait for all tasks to be cancelled
		if tasks:
			await asyncio.gather(*tasks, return_exceptions=True)


async def textual_interface(config: dict[str, Any]):
	"""Run the Textual interface."""
	# Prevent browser_use from setting up logging at import time
	os.environ['BROWSER_USE_SETUP_LOGGING'] = 'false'

	logger = logging.getLogger('browser_use.startup')

	# Set up logging for Textual UI - prevent any logging to stdout
	def setup_textual_logging():
		# Replace all handlers with null handler
		root_logger = logging.getLogger()
		for handler in root_logger.handlers:
			root_logger.removeHandler(handler)

		# Add null handler to ensure no output to stdout/stderr
		null_handler = logging.NullHandler()
		root_logger.addHandler(null_handler)
		logger.debug('Logging configured for Textual UI')

	logger.debug('Setting up Browser, Controller, and LLM...')

	# Step 1: Initialize BrowserSession with config
	logger.debug('Initializing BrowserSession...')
	try:
		# Get browser config from the config dict
		browser_config = config.get('browser', {})

		logger.info('Browser type: chromium')  # BrowserSession only supports chromium
		if browser_config.get('executable_path'):
			logger.info(f'Browser binary: {browser_config["executable_path"]}')
		if browser_config.get('headless'):
			logger.info('Browser mode: headless')
		else:
			logger.info('Browser mode: visible')

		# Create BrowserSession directly with config parameters
		# Remove None values from browser_config
		browser_config = {k: v for k, v in browser_config.items() if v is not None}
		# Create BrowserProfile with user_data_dir
		profile = BrowserProfile(user_data_dir=str(USER_DATA_DIR), **browser_config)
		browser_session = BrowserSession(
			browser_profile=profile,
		)
		logger.debug('BrowserSession initialized successfully')

		# Set up FIFO logging pipes for streaming logs to UI
		try:
			from browser_use.logging_config import setup_log_pipes

			setup_log_pipes(session_id=browser_session.id)
			logger.debug(f'FIFO logging pipes set up for session {browser_session.id[-4:]}')
		except Exception as e:
			logger.debug(f'Could not set up FIFO logging pipes: {e}')

		# Browser version logging not available with CDP implementation
	except Exception as e:
		logger.error(f'Error initializing BrowserSession: {str(e)}', exc_info=True)
		raise RuntimeError(f'Failed to initialize BrowserSession: {str(e)}')

	# Step 3: Initialize Controller
	logger.debug('Initializing Controller...')
	try:
		controller = Controller()
		logger.debug('Controller initialized successfully')
	except Exception as e:
		logger.error(f'Error initializing Controller: {str(e)}', exc_info=True)
		raise RuntimeError(f'Failed to initialize Controller: {str(e)}')

	# Step 4: Get LLM
	logger.debug('Getting LLM...')
	try:
		# Ensure setup_logging is not called when importing modules
		os.environ['BROWSER_USE_SETUP_LOGGING'] = 'false'
		llm = get_llm(config)
		# Log LLM details
		model_name = getattr(llm, 'model_name', None) or getattr(llm, 'model', 'Unknown model')
		provider = llm.__class__.__name__
		temperature = getattr(llm, 'temperature', 0.0)
		logger.info(f'LLM: {provider} ({model_name}), temperature: {temperature}')
		logger.debug(f'LLM initialized successfully: {provider}')
	except Exception as e:
		logger.error(f'Error getting LLM: {str(e)}', exc_info=True)
		raise RuntimeError(f'Failed to initialize LLM: {str(e)}')

	logger.debug('Initializing BrowserUseApp instance...')
	try:
		app = BrowserUseApp(config)
		# Pass the initialized components to the app
		app.browser_session = browser_session
		app.controller = controller
		app.llm = llm

		# Set up event bus listener now that browser session is available
		# Note: This needs to be called before run_async() but after browser_session is set
		# We'll defer this to on_mount() since it needs the widgets to be available

		# Configure logging for Textual UI before going fullscreen
		setup_textual_logging()

		# Log browser and model configuration that will be used
		browser_type = 'Chromium'  # BrowserSession only supports Chromium
		model_name = config.get('model', {}).get('name', 'auto-detected')
		headless = config.get('browser', {}).get('headless', False)
		headless_str = 'headless' if headless else 'visible'

		logger.info(f'Preparing {browser_type} browser ({headless_str}) with {model_name} LLM')

		logger.debug('Starting Textual app with run_async()...')
		# No more logging after this point as we're in fullscreen mode
		await app.run_async()
	except Exception as e:
		logger.error(f'Error in textual_interface: {str(e)}', exc_info=True)
		# Note: We don't close the browser session here to avoid duplicate stop() calls
		# The browser session will be cleaned up by its __del__ method if needed
		raise


async def run_auth_command():
	"""Run the authentication command with dummy task in UI."""
	import asyncio
	import os

	from browser_use.sync.auth import DeviceAuthClient

	print('🔐 Browser Use Cloud Authentication')
	print('=' * 40)

	# Ensure cloud sync is enabled (should be default, but make sure)
	os.environ['BROWSER_USE_CLOUD_SYNC'] = 'true'

	auth_client = DeviceAuthClient()

	print('🔍 Debug: Checking authentication status...')
	print(f'    API Token: {"✅ Present" if auth_client.api_token else "❌ Missing"}')
	print(f'    User ID: {auth_client.user_id}')
	print(f'    Is Authenticated: {auth_client.is_authenticated}')
	if auth_client.auth_config.authorized_at:
		print(f'    Authorized at: {auth_client.auth_config.authorized_at}')
	print()

	# Check if already authenticated
	if auth_client.is_authenticated:
		print('✅ Already authenticated!')
		print(f'   User ID: {auth_client.user_id}')
		print(f'   Authenticated at: {auth_client.auth_config.authorized_at}')

		# Show cloud URL if possible
		frontend_url = CONFIG.BROWSER_USE_CLOUD_UI_URL or auth_client.base_url.replace('//api.', '//cloud.')
		print(f'\n🌐 View your runs at: {frontend_url}')
		return

	print('🚀 Starting authentication flow...')
	print('   This will open a browser window for you to sign in.')
	print()

	# Initialize variables for exception handling
	task_id = None
	sync_service = None

	try:
		# Create authentication flow with dummy task
		from uuid_extensions import uuid7str

		from browser_use.agent.cloud_events import (
			CreateAgentSessionEvent,
			CreateAgentStepEvent,
			CreateAgentTaskEvent,
			UpdateAgentTaskEvent,
		)
		from browser_use.sync.service import CloudSync

		# IDs for our session and task
		session_id = uuid7str()
		task_id = uuid7str()

		# Create special sync service that allows auth events
		sync_service = CloudSync(allow_session_events_for_auth=True)
		sync_service.set_auth_flow_active()  # Explicitly enable auth flow
		sync_service.session_id = session_id  # Set session ID for auth context
		sync_service.auth_client = auth_client  # Use the same auth client instance!

		# 1. Create session (like main branch does at start)
		session_event = CreateAgentSessionEvent(
			id=session_id,
			user_id=auth_client.temp_user_id,
			browser_session_id=uuid7str(),
			browser_session_live_url='',
			browser_session_cdp_url='',
			device_id=auth_client.device_id,
			browser_state={
				'viewport': {'width': 1280, 'height': 720},
				'user_agent': None,
				'headless': True,
				'initial_url': None,
				'final_url': None,
				'total_pages_visited': 0,
				'session_duration_seconds': 0,
			},
			browser_session_data={
				'cookies': [],
				'secrets': {},
				'allowed_domains': [],
			},
		)
		await sync_service.handle_event(session_event)

		# Brief delay to ensure session is created in backend before sending task
		await asyncio.sleep(0.5)

		# 2. Create task (like main branch does at start)
		task_event = CreateAgentTaskEvent(
			id=task_id,
			agent_session_id=session_id,
			llm_model='auth-flow',
			task='🔐 Complete authentication and join the browser-use community',
			user_id=auth_client.temp_user_id,
			device_id=auth_client.device_id,
			done_output=None,
			user_feedback_type=None,
			user_comment=None,
			gif_url=None,
		)
		await sync_service.handle_event(task_event)

		# Longer delay to ensure task is created in backend before sending step event
		await asyncio.sleep(1.0)

		# 3. Run authentication with timeout
		print('⏳ Waiting for authentication... (this may take up to 2 minutes for testing)')
		print('   Complete the authentication in your browser, then this will continue automatically.')
		print()

		try:
			print('🔧 Debug: Starting authentication process...')
			print(f'    Original auth client authenticated: {auth_client.is_authenticated}')
			print(f'    Sync service auth client authenticated: {sync_service.auth_client.is_authenticated}')
			print(f'    Same auth client? {auth_client is sync_service.auth_client}')
			print(f'    Session ID: {sync_service.session_id}')

			# Create a task to show periodic status updates
			async def show_auth_progress():
				for i in range(1, 25):  # Show updates every 5 seconds for 2 minutes
					await asyncio.sleep(5)
					fresh_check = DeviceAuthClient()
					print(f'⏱️  Waiting for authentication... ({i * 5}s elapsed)')
					print(f'    Status: {"✅ Authenticated" if fresh_check.is_authenticated else "⏳ Still waiting"}')
					if fresh_check.is_authenticated:
						print('🎉 Authentication detected! Completing...')
						break

			# Run authentication and progress updates concurrently
			auth_start_time = asyncio.get_event_loop().time()
			auth_task = asyncio.create_task(sync_service.authenticate(show_instructions=True))
			progress_task = asyncio.create_task(show_auth_progress())

			# Wait for authentication to complete, with timeout
			success = await asyncio.wait_for(auth_task, timeout=120.0)  # 2 minutes for initial testing
			progress_task.cancel()  # Stop the progress updates

			auth_duration = asyncio.get_event_loop().time() - auth_start_time
			print(f'🔧 Debug: Authentication returned: {success} (took {auth_duration:.1f}s)')

		except TimeoutError:
			print('⏱️ Authentication timed out after 2 minutes.')
			print('   Checking if authentication completed in background...')

			# Create a fresh auth client to check current status
			fresh_auth_client = DeviceAuthClient()
			print('🔧 Debug: Fresh auth client check:')
			print(f'    API Token: {"✅ Present" if fresh_auth_client.api_token else "❌ Missing"}')
			print(f'    Is Authenticated: {fresh_auth_client.is_authenticated}')

			if fresh_auth_client.is_authenticated:
				print('✅ Authentication was successful!')
				success = True
				# Update the sync service's auth client
				sync_service.auth_client = fresh_auth_client
			else:
				print('❌ Authentication not completed. Please try again.')
				success = False
		except Exception as e:
			print(f'❌ Authentication error: {type(e).__name__}: {e}')
			import traceback

			print(f'📄 Full traceback: {traceback.format_exc()}')
			success = False

		if success:
			# 4. Send step event to show progress (like main branch during execution)
			# Use the sync service's auth client which has the updated user_id
			step_event = CreateAgentStepEvent(
				# Remove explicit ID - let it auto-generate to avoid backend validation issues
				user_id=auth_client.temp_user_id,  # Use same temp user_id as task for consistency
				device_id=auth_client.device_id,  # Use consistent device_id
				agent_task_id=task_id,
				step=1,
				actions=[
					{
						'click': {
							'coordinate': [800, 400],
							'description': 'Click on Star button',
							'success': True,
						},
						'done': {
							'success': True,
							'text': '⭐ Starred browser-use/browser-use repository! Welcome to the community!',
						},
					}
				],
				next_goal='⭐ Star browser-use GitHub repository to join the community',
				evaluation_previous_goal='Authentication completed successfully',
				memory='User authenticated with Browser Use Cloud and is now part of the community',
				screenshot_url=None,
				url='https://github.com/browser-use/browser-use',
			)
			print('📤 Sending dummy step event...')
			await sync_service.handle_event(step_event)

			# Small delay to ensure step is processed before completion
			await asyncio.sleep(0.5)

			# 5. Complete task (like main branch does at end)
			completion_event = UpdateAgentTaskEvent(
				id=task_id,
				user_id=auth_client.temp_user_id,  # Use same temp user_id as task for consistency
				device_id=auth_client.device_id,  # Use consistent device_id
				done_output="🎉 Welcome to Browser Use! You're now authenticated and part of our community. ⭐ Your future tasks will sync to the cloud automatically.",
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
			)
			await sync_service.handle_event(completion_event)

			print('🎉 Authentication successful!')
			print('   Future browser-use runs will now sync to the cloud.')
		else:
			# Failed - still complete the task with failure message
			completion_event = UpdateAgentTaskEvent(
				id=task_id,
				user_id=auth_client.temp_user_id,  # Still temp user since auth failed
				device_id=auth_client.device_id,
				done_output='❌ Authentication failed. Please try again.',
				user_feedback_type=None,
				user_comment=None,
				gif_url=None,
			)
			await sync_service.handle_event(completion_event)

			print('❌ Authentication failed.')
			print('   Please try again or check your internet connection.')

	except Exception as e:
		print(f'❌ Authentication error: {e}')
		# Still try to complete the task in UI with error message
		if task_id and sync_service:
			try:
				from browser_use.agent.cloud_events import UpdateAgentTaskEvent

				completion_event = UpdateAgentTaskEvent(
					id=task_id,
					user_id=auth_client.temp_user_id,
					device_id=auth_client.device_id,
					done_output=f'❌ Authentication error: {e}',
					user_feedback_type=None,
					user_comment=None,
					gif_url=None,
				)
				await sync_service.handle_event(completion_event)
			except Exception:
				pass  # Don't fail if we can't send the error event
		sys.exit(1)


@click.group(invoke_without_command=True)
@click.option('--version', is_flag=True, help='Print version and exit')
@click.option('--model', type=str, help='Model to use (e.g., gpt-5-mini, claude-4-sonnet, gemini-2.5-flash)')
@click.option('--debug', is_flag=True, help='Enable verbose startup logging')
@click.option('--headless', is_flag=True, help='Run browser in headless mode', default=None)
@click.option('--window-width', type=int, help='Browser window width')
@click.option('--window-height', type=int, help='Browser window height')
@click.option(
	'--user-data-dir', type=str, help='Path to Chrome user data directory (e.g. ~/Library/Application Support/Google/Chrome)'
)
@click.option('--profile-directory', type=str, help='Chrome profile directory name (e.g. "Default", "Profile 1")')
@click.option('--cdp-url', type=str, help='Connect to existing Chrome via CDP URL (e.g. http://localhost:9222)')
@click.option('--proxy-url', type=str, help='Proxy server for Chromium traffic (e.g. http://host:8080 or socks5://host:1080)')
@click.option('--no-proxy', type=str, help='Comma-separated hosts to bypass proxy (e.g. localhost,127.0.0.1,*.internal)')
@click.option('--proxy-username', type=str, help='Proxy auth username')
@click.option('--proxy-password', type=str, help='Proxy auth password')
@click.option('-p', '--prompt', type=str, help='Run a single task without the TUI (headless mode)')
@click.option('--mcp', is_flag=True, help='Run as MCP server (exposes JSON RPC via stdin/stdout)')
@click.pass_context
def main(ctx: click.Context, debug: bool = False, **kwargs):
	"""Browser Use - AI Agent for Web Automation

	Run without arguments to start the interactive TUI.
	"""

	if ctx.invoked_subcommand is None:
		# No subcommand, run the main interface
		run_main_interface(ctx, debug, **kwargs)


def run_main_interface(ctx: click.Context, debug: bool = False, **kwargs):
	"""Run the main browser-use interface"""

	if kwargs['version']:
		from importlib.metadata import version

		print(version('browser-use'))
		sys.exit(0)

	# Check if MCP server mode is activated
	if kwargs.get('mcp'):
		# Capture telemetry for MCP server mode via CLI (suppress any logging from this)
		try:
			telemetry = ProductTelemetry()
			telemetry.capture(
				CLITelemetryEvent(
					version=get_browser_use_version(),
					action='start',
					mode='mcp_server',
				)
			)
		except Exception:
			# Ignore telemetry errors in MCP mode to prevent any stdout contamination
			pass
		# Run as MCP server
		from browser_use.mcp.server import main as mcp_main

		asyncio.run(mcp_main())
		return

	# Check if prompt mode is activated
	if kwargs.get('prompt'):
		# Set environment variable for prompt mode before running
		os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'result'
		# Run in non-interactive mode
		asyncio.run(run_prompt_mode(kwargs['prompt'], ctx, debug))
		return

	# Configure console logging
	console_handler = logging.StreamHandler(sys.stdout)
	console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%H:%M:%S'))

	# Configure root logger
	root_logger = logging.getLogger()
	root_logger.setLevel(logging.INFO if not debug else logging.DEBUG)
	root_logger.addHandler(console_handler)

	logger = logging.getLogger('browser_use.startup')
	logger.info('Starting Browser-Use initialization')
	if debug:
		logger.debug(f'System info: Python {sys.version.split()[0]}, Platform: {sys.platform}')

	logger.debug('Loading environment variables from .env file...')
	load_dotenv()
	logger.debug('Environment variables loaded')

	# Load user configuration
	logger.debug('Loading user configuration...')
	try:
		config = load_user_config()
		logger.debug(f'User configuration loaded from {CONFIG.BROWSER_USE_CONFIG_FILE}')
	except Exception as e:
		logger.error(f'Error loading user configuration: {str(e)}', exc_info=True)
		print(f'Error loading configuration: {str(e)}')
		sys.exit(1)

	# Update config with command-line arguments
	logger.debug('Updating configuration with command line arguments...')
	try:
		config = update_config_with_click_args(config, ctx)
		logger.debug('Configuration updated')
	except Exception as e:
		logger.error(f'Error updating config with command line args: {str(e)}', exc_info=True)
		print(f'Error updating configuration: {str(e)}')
		sys.exit(1)

	# Save updated config
	logger.debug('Saving user configuration...')
	try:
		save_user_config(config)
		logger.debug('Configuration saved')
	except Exception as e:
		logger.error(f'Error saving user configuration: {str(e)}', exc_info=True)
		print(f'Error saving configuration: {str(e)}')
		sys.exit(1)

	# Setup handlers for console output before entering Textual UI
	logger.debug('Setting up handlers for Textual UI...')

	# Log browser and model configuration that will be used
	browser_type = 'Chromium'  # BrowserSession only supports Chromium
	model_name = config.get('model', {}).get('name', 'auto-detected')
	headless = config.get('browser', {}).get('headless', False)
	headless_str = 'headless' if headless else 'visible'

	logger.info(f'Preparing {browser_type} browser ({headless_str}) with {model_name} LLM')

	try:
		# Run the Textual UI interface - now all the initialization happens before we go fullscreen
		logger.debug('Starting Textual UI interface...')
		asyncio.run(textual_interface(config))
	except Exception as e:
		# Restore console logging for error reporting
		root_logger.setLevel(logging.INFO)
		for handler in root_logger.handlers:
			root_logger.removeHandler(handler)
		root_logger.addHandler(console_handler)

		logger.error(f'Error initializing Browser-Use: {str(e)}', exc_info=debug)
		print(f'\nError launching Browser-Use: {str(e)}')
		if debug:
			import traceback

			traceback.print_exc()
		sys.exit(1)


@main.command()
def auth():
	"""Authenticate with Browser Use Cloud to sync your runs"""
	asyncio.run(run_auth_command())


if __name__ == '__main__':
	main()
