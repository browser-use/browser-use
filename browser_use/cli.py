import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

try:
	import click
	from textual import events
	from textual.app import App, ComposeResult
	from textual.binding import Binding
	from textual.containers import Container, HorizontalGroup, VerticalScroll
	from textual.widgets import Footer, Header, Input, Label, Link, RichLog, Static
except ImportError:
	print('⚠️ CLI addon is not installed. Please install it with: `pip install browser-use[cli]` and try again.')
	sys.exit(1)

import langchain_anthropic
import langchain_google_genai
import langchain_openai
from patchright.async_api import async_playwright

try:
	import readline

	READLINE_AVAILABLE = True
except ImportError:
	# readline not available on Windows by default
	READLINE_AVAILABLE = False


os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'result'

from browser_use import Agent, Controller
from browser_use.agent.views import AgentSettings
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserChannel
from browser_use.logging_config import addLoggingLevel

# Paths
USER_CONFIG_DIR = Path.home() / '.config' / 'browseruse'
USER_CONFIG_FILE = USER_CONFIG_DIR / 'config.json'
CHROME_PROFILES_DIR = USER_CONFIG_DIR / 'profiles'
USER_DATA_DIR = CHROME_PROFILES_DIR / 'default'

# Default User settings
MAX_HISTORY_LENGTH = 100

# Ensure directories exist
USER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)


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
	"""Return default configuration dictionary."""
	return {
		'model': {
			'name': None,
			'temperature': 0.0,
			'api_keys': {
				'OPENAI_API_KEY': os.getenv('OPENAI_API_KEY', ''),
				'ANTHROPIC_API_KEY': os.getenv('ANTHROPIC_API_KEY', ''),
				'GOOGLE_API_KEY': os.getenv('GOOGLE_API_KEY', ''),
				'DEEPSEEK_API_KEY': os.getenv('DEEPSEEK_API_KEY', ''),
				'GROK_API_KEY': os.getenv('GROK_API_KEY', ''),
			},
		},
		'agent': {},  # AgentSettings will use defaults
		'browser': {
			'headless': True,
			'keep_alive': True,
			'ignore_https_errors': False,
		},
		'command_history': [],
	}


def load_user_config() -> dict[str, Any]:
	"""Load user configuration from file."""
	if not USER_CONFIG_FILE.exists():
		# Create default config
		config = get_default_config()
		save_user_config(config)
		return config

	try:
		with open(USER_CONFIG_FILE) as f:
			data = json.load(f)
			# Ensure data is a dictionary, not a list
			if isinstance(data, list):
				# If it's a list, it's probably just command history from previous version
				config = get_default_config()
				config['command_history'] = data  # Use the list as command history
				return config
			return data
	except (json.JSONDecodeError, FileNotFoundError):
		# If file is corrupted, start with empty config
		return get_default_config()


def save_user_config(config: dict[str, Any]) -> None:
	"""Save user configuration to file."""
	# Ensure command history doesn't exceed maximum length
	if 'command_history' in config and isinstance(config['command_history'], list):
		if len(config['command_history']) > MAX_HISTORY_LENGTH:
			config['command_history'] = config['command_history'][-MAX_HISTORY_LENGTH:]

	with open(USER_CONFIG_FILE, 'w') as f:
		json.dump(config, f, indent=2)


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
	# Set API keys from config if available
	api_keys = config.get('model', {}).get('api_keys', {})
	model_name = config.get('model', {}).get('name')
	temperature = config.get('model', {}).get('temperature', 0.0)

	# Set environment variables if they're in the config but not in the environment
	if api_keys.get('openai') and not os.getenv('OPENAI_API_KEY'):
		os.environ['OPENAI_API_KEY'] = api_keys['openai']
	if api_keys.get('anthropic') and not os.getenv('ANTHROPIC_API_KEY'):
		os.environ['ANTHROPIC_API_KEY'] = api_keys['anthropic']
	if api_keys.get('google') and not os.getenv('GOOGLE_API_KEY'):
		os.environ['GOOGLE_API_KEY'] = api_keys['google']

	if model_name:
		if model_name.startswith('gpt'):
			if not os.getenv('OPENAI_API_KEY'):
				print('⚠️  OpenAI API key not found. Please update your config or set OPENAI_API_KEY environment variable.')
				sys.exit(1)
			return langchain_openai.ChatOpenAI(model=model_name, temperature=temperature)
		elif model_name.startswith('claude'):
			if not os.getenv('ANTHROPIC_API_KEY'):
				print('⚠️  Anthropic API key not found. Please update your config or set ANTHROPIC_API_KEY environment variable.')
				sys.exit(1)
			return langchain_anthropic.ChatAnthropic(model=model_name, temperature=temperature)
		elif model_name.startswith('gemini'):
			if not os.getenv('GOOGLE_API_KEY'):
				print('⚠️  Google API key not found. Please update your config or set GOOGLE_API_KEY environment variable.')
				sys.exit(1)
			return langchain_google_genai.ChatGoogleGenerativeAI(model=model_name, temperature=temperature)

	# Auto-detect based on available API keys
	if os.getenv('OPENAI_API_KEY'):
		return langchain_openai.ChatOpenAI(model='gpt-4o', temperature=temperature)
	elif os.getenv('ANTHROPIC_API_KEY'):
		return langchain_anthropic.ChatAnthropic(model='claude-3.5-sonnet-exp', temperature=temperature)
	elif os.getenv('GOOGLE_API_KEY'):
		return langchain_google_genai.ChatGoogleGenerativeAI(model='gemini-2.0-flash-lite', temperature=temperature)
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
	}
	
	#top-panels {
		layout: horizontal;
		height: auto;
		width: 100%;
		min-height: 5;
	}
	
	#browser-panel, #model-panel {
		width: 1fr;
		height: auto;
		border: solid $primary-darken-2;
		padding: 1;
		overflow: auto;
		margin: 0 1 0 0;
		padding: 1;
	}
	
	#tasks-panel {
		width: 100%;
		height: 1fr;
		min-height: 20;
		max-height: 60vh;
		border: solid $primary-darken-2;
		padding: 1;
		overflow-y: scroll;
		margin: 1 0 0 0;
	}
	
	#browser-panel {
		border-left: solid $primary-darken-2;
	}
	
	#results-container {
		display: none;
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
	
	#working-panel {
		border: solid $warning;
		padding: 1;
		margin: 1 0;
	}
	
	#completion-panel {
		border: solid $success;
		padding: 1;
		margin: 1 0;
	}
	
	#results-container {
		height: 1fr;
		overflow: auto;
		border: none;
	}
	
	#results-log {
		height: auto;
		overflow-y: scroll;
		background: $surface;
		color: $text;
		width: 100%;
	}
	
	.log-entry {
		margin: 0;
		padding: 0;
	}
	
	#browser-info, #model-info, #tasks-info {
		height: auto;
		margin: 0;
		padding: 0;
		background: transparent;
		overflow-y: auto;
		min-height: 5;
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
		self.browser_session = None  # Will be set before app.run_async()
		self.controller = None  # Will be set before app.run_async()
		self.agent = None
		self.llm = None  # Will be set before app.run_async()
		self.task_history = config.get('command_history', [])
		# Track current position in history for up/down navigation
		self.history_index = len(self.task_history)

	def setup_richlog_logging(self) -> None:
		"""Set up logging to redirect to RichLog widget instead of stdout."""
		# Try to add RESULT level if it doesn't exist
		try:
			addLoggingLevel('RESULT', 35)
		except AttributeError:
			pass  # Level already exists, which is fine

		# Get the RichLog widget
		rich_log = self.query_one('#results-log')

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

		# Clear all existing handlers and add only our richlog handler
		root.handlers = []
		root.addHandler(log_handler)

		# Set log level based on environment variable
		if log_type == 'result':
			root.setLevel('RESULT')
		elif log_type == 'debug':
			root.setLevel(logging.DEBUG)
		else:
			root.setLevel(logging.INFO)

		# Configure browser_use logger
		browser_use_logger = logging.getLogger('browser_use')
		browser_use_logger.propagate = False  # Don't propagate to root logger
		browser_use_logger.handlers = [log_handler]  # Replace any existing handlers
		browser_use_logger.setLevel(root.level)

		# Silence third-party loggers
		for logger_name in [
			'WDM',
			'httpx',
			'selenium',
			'playwright',
			'urllib3',
			'asyncio',
			'langchain',
			'openai',
			'httpcore',
			'charset_normalizer',
			'anthropic._base_client',
			'PIL.PngImagePlugin',
			'trafilatura.htmlprocessing',
			'trafilatura',
		]:
			third_party = logging.getLogger(logger_name)
			third_party.setLevel(logging.ERROR)
			third_party.propagate = False
			third_party.handlers = []  # Clear any existing handlers

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
			input_field = self.query_one('#task-input')
			input_field.focus()
			logger.debug('Input field focused')
		except Exception as e:
			logger.error(f'Error focusing input field: {str(e)}', exc_info=True)
			# Non-critical, continue

		# Step 5: Start continuous info panel updates
		logger.debug('Starting info panel updates...')
		try:
			self.update_info_panels()
			logger.debug('Info panel updates started')
		except Exception as e:
			logger.error(f'Error starting info panel updates: {str(e)}', exc_info=True)
			# Non-critical, continue

		logger.debug('on_mount() completed successfully')

	def on_input_key_up(self, event: events.Key) -> None:
		"""Handle up arrow key in the input field."""
		# Check if event is from the input field
		if event.sender.id != 'task-input':
			return

		# Only process if we have history
		if not self.task_history:
			return

		# Move back in history if possible
		if self.history_index > 0:
			self.history_index -= 1
			self.query_one('#task-input').value = self.task_history[self.history_index]
			# Move cursor to end of text
			self.query_one('#task-input').cursor_position = len(self.query_one('#task-input').value)

		# Prevent default behavior (cursor movement)
		event.prevent_default()
		event.stop()

	def on_input_key_down(self, event: events.Key) -> None:
		"""Handle down arrow key in the input field."""
		# Check if event is from the input field
		if event.sender.id != 'task-input':
			return

		# Only process if we have history
		if not self.task_history:
			return

		# Move forward in history or clear input if at the end
		if self.history_index < len(self.task_history) - 1:
			self.history_index += 1
			self.query_one('#task-input').value = self.task_history[self.history_index]
			# Move cursor to end of text
			self.query_one('#task-input').cursor_position = len(self.query_one('#task-input').value)
		elif self.history_index == len(self.task_history) - 1:
			# At the end of history, go to "new line" state
			self.history_index += 1
			self.query_one('#task-input').value = ''

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
		"""Hide the intro panels, show info panels, and expand the log view."""
		try:
			# Get the panels
			logo_panel = self.query_one('#logo-panel')
			links_panel = self.query_one('#links-panel')
			paths_panel = self.query_one('#paths-panel')
			info_panels = self.query_one('#info-panels')
			tasks_panel = self.query_one('#tasks-panel')
			# Hide intro panels if they're visible and show info panels
			if logo_panel.display:
				# Log for debugging
				logging.info('Hiding intro panels and showing info panels')

				logo_panel.display = False
				links_panel.display = False
				paths_panel.display = False

				# Show info panels
				info_panels.display = True
				tasks_panel.display = True

				# Make results container take full height
				results_container = self.query_one('#results-container')
				results_container.styles.height = '1fr'

				# Configure the log
				results_log = self.query_one('#results-log')
				results_log.styles.height = 'auto'

				logging.info('Panels should now be visible')
		except Exception as e:
			logging.error(f'Error in hide_intro_panels: {str(e)}')

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
		browser_info = self.query_one('#browser-info')
		browser_info.clear()

		# Try to use the agent's browser session if available
		browser_session = self.browser_session
		if hasattr(self, 'agent') and self.agent and hasattr(self.agent, 'browser_session'):
			browser_session = self.agent.browser_session

		if browser_session:
			try:
				# Check if browser session has a browser context
				if not hasattr(browser_session, 'browser_context') or browser_session.browser_context is None:
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
				elif browser_session.wss_url:
					connection_type = 'WSS'
				elif browser_session.browser_profile.executable_path:
					connection_type = 'user-provided'

				# Get window size details from browser_profile
				window_width = None
				window_height = None
				if browser_session.browser_profile.viewport:
					window_width = browser_session.browser_profile.viewport.get('width')
					window_height = browser_session.browser_profile.viewport.get('height')

				# Try to get browser PID
				browser_pid = 'Unknown'
				connected = False
				browser_status = '[red]Disconnected[/]'

				try:
					# Check if browser PID is available
					if hasattr(browser_session, 'browser_pid') and browser_session.browser_pid:
						browser_pid = str(browser_session.browser_pid)
						connected = True
						browser_status = '[green]Connected[/]'
					# Otherwise just check if we have a browser context
					elif browser_session.browser_context is not None:
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
					if browser_session.agent_current_page:
						current_url = (
							browser_session.agent_current_page.url.replace('https://', '')
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
		model_info = self.query_one('#model-info')
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
				memory_str = '+ memory ' if self.agent.enable_memory else ''
				planner_str = '+ planner' if self.agent.settings.planner_llm else ''
				model_info.write(
					f'[white]LLM:[/] [blue]{self.llm.__class__.__name__} [yellow]{model_name}[/] {temp_str}{vision_str}{memory_str}{planner_str}'
				)
			else:
				model_info.write(f'[white]LLM:[/] [blue]{self.llm.__class__.__name__} [yellow]{model_name}[/]')

			# Show token usage statistics if agent exists and has history
			if self.agent and hasattr(self.agent, 'state') and hasattr(self.agent.state, 'history'):
				# Get total tokens used
				total_tokens = self.agent.state.history.total_input_tokens()
				model_info.write(f'[white]Input tokens:[/] [green]{total_tokens:,}[/]')

				# Calculate tokens per step
				num_steps = len(self.agent.state.history.history)
				if num_steps > 0:
					avg_tokens_per_step = total_tokens / num_steps
					model_info.write(f'[white]Avg tokens/step:[/] [green]{avg_tokens_per_step:,.1f}[/]')

					# Get the last step metadata to show the most recent LLM response time
				if num_steps > 0 and self.agent.state.history.history[-1].metadata:
					last_step = self.agent.state.history.history[-1]
					step_duration = last_step.metadata.duration_seconds
					step_tokens = last_step.metadata.input_tokens

					if step_tokens > 0:
						tokens_per_second = step_tokens / step_duration if step_duration > 0 else 0
						model_info.write(f'[white]Avg tokens/sec:[/] [magenta]{tokens_per_second:.1f}[/]')

				# Show total duration
				total_duration = self.agent.state.history.total_duration_seconds()
				if total_duration > 0:
					model_info.write(f'[white]Total Duration:[/] [magenta]{total_duration:.2f}s[/]')

					# Calculate response time metrics
					model_info.write(f'[white]Last Step Duration:[/] [magenta]{step_duration:.2f}s[/]')

				# Add current state information
				if hasattr(self.agent, 'running'):
					if self.agent.running:
						model_info.write('[yellow]LLM is thinking[blink]...[/][/]')
					elif hasattr(self.agent, 'state') and hasattr(self.agent.state, 'paused') and self.agent.state.paused:
						model_info.write('[orange]LLM paused[/]')
		else:
			model_info.write('[red]Model not initialized[/]')

	def update_tasks_panel(self) -> None:
		"""Update tasks information panel with details about the tasks and steps hierarchy."""
		tasks_info = self.query_one('#tasks-info')
		tasks_info.clear()

		if self.agent:
			# Check if agent has tasks
			task_history = []
			message_history = []

			# Try to extract tasks by looking at message history
			if hasattr(self.agent, '_message_manager') and self.agent._message_manager:
				message_history = self.agent._message_manager.state.history.messages

				# Extract original task(s)
				original_tasks = []
				for msg in message_history:
					if hasattr(msg, 'message') and hasattr(msg.message, 'content'):
						content = msg.message.content
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
				history_items = self.agent.state.history.history

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
							# Show memory (context) for this step
							memory = item.model_output.current_state.memory
							if memory:
								memory_lines = memory.strip().split('\n')
								memory_summary = memory_lines[0]
								tasks_info.write(f'   [dim]Memory:[/] {memory_summary}')

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
			if hasattr(self.agent, 'running') and self.agent.running:
				tasks_info.write('[yellow]Agent is actively working[blink]...[/][/]')
			elif hasattr(self.agent, 'state') and hasattr(self.agent.state, 'paused') and self.agent.state.paused:
				tasks_info.write('[orange]Agent is paused (press Enter to resume)[/]')
		else:
			tasks_info.write('[dim]Agent not initialized[/]')

		# Force scroll to bottom
		tasks_panel = self.query_one('#tasks-panel')
		tasks_panel.scroll_end(animate=False)

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

		# Start continuous updates of all info panels
		self.update_info_panels()

		# Clear the log to start fresh
		rich_log = self.query_one('#results-log')
		rich_log.clear()

		if self.agent is None:
			self.agent = Agent(
				task=task,
				llm=self.llm,
				controller=self.controller,
				browser_session=self.browser_session,
				source='cli',
				**agent_settings.model_dump(),
			)
			# Update our browser_session reference to point to the agent's
			if hasattr(self.agent, 'browser_session'):
				self.browser_session = self.agent.browser_session
		else:
			self.agent.add_new_task(task)

		# Let the agent run in the background
		async def agent_task_worker() -> None:
			logger.debug('\n🚀 Working on task: %s', task)

			# Set flags to indicate the agent is running
			self.agent.running = True
			self.agent.last_response_time = 0

			# Panel updates are already happening via the timer in update_info_panels

			try:
				# Run the agent task, redirecting output to RichLog through our handler
				await self.agent.run()
			except Exception as e:
				logger.error('\nError running agent: %s', str(e))
			finally:
				# Clear the running flag
				self.agent.running = False

				# No need to call update_info_panels() here as it's already updating via timer

				logger.debug('\n✅ Task completed!')

				# Make sure the task input container is visible
				task_input_container = self.query_one('#task-input-container')
				task_input_container.display = True

				# Refocus the input field
				input_field = self.query_one('#task-input')
				input_field.focus()

				# Ensure the input is visible by scrolling to it
				self.call_after_refresh(self.scroll_to_input)

		# Run the worker
		self.run_worker(agent_task_worker, name='agent_task')

	def action_input_history_prev(self) -> None:
		"""Navigate to the previous item in command history."""
		# Only process if we have history and input is focused
		input_field = self.query_one('#task-input')
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
		input_field = self.query_one('#task-input')
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
		# Close the browser session if it exists
		if self.browser_session:
			try:
				await self.browser_session.close()
				logging.debug('Browser session closed successfully')
			except Exception as e:
				logging.error(f'Error closing browser session: {str(e)}')

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

			# Information panels (hidden by default)
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
				f' ⚙️  Settings & history saved to:    {str(USER_CONFIG_FILE.resolve()).replace(str(Path.home()), "~")}\n'
				f' 📁 Outputs & recordings saved to:  {str(Path(".").resolve()).replace(str(Path.home()), "~")}',
				id='paths-panel',
				markup=True,
			)

			# Results view with scrolling (place this before input to make input sticky at bottom)
			with VerticalScroll(id='results-container'):
				yield RichLog(highlight=True, markup=True, id='results-log', wrap=True, auto_scroll=True)

			# Task input container (now at the bottom)
			with Container(id='task-input-container'):
				yield Label('🔍 What would you like me to do on the web?', id='task-label')
				yield Input(placeholder='Enter your task...', id='task-input')

		yield Footer()


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

	try:
		# Load config
		config = load_user_config()
		config = update_config_with_click_args(config, ctx)

		# Get LLM
		llm = get_llm(config)

		# Get agent settings from config
		agent_settings = AgentSettings.model_validate(config.get('agent', {}))

		# Create browser session with config parameters
		browser_config = config.get('browser', {})
		browser_session = BrowserSession(stealth=True, **browser_config)

		# Create and run agent
		agent = Agent(
			task=prompt,
			llm=llm,
			browser_session=browser_session,
			source='cli',
			**agent_settings.model_dump(),
		)

		await agent.run()

		# Close browser session
		await browser_session.close()

	except Exception as e:
		if debug:
			import traceback

			traceback.print_exc()
		else:
			print(f'Error: {str(e)}', file=sys.stderr)
		sys.exit(1)


async def textual_interface(config: dict[str, Any]):
	"""Run the Textual interface."""
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
		browser_session = BrowserSession(
			**browser_config,
			playwright=(await async_playwright().start()),
			channel=BrowserChannel.CHROME,
			user_data_dir='~/.browseruse/profiles/default/cli',
		)
		logger.debug('BrowserSession initialized successfully')

		# Log browser version if available
		try:
			if hasattr(browser_session, 'version') and browser_session.version:
				logger.info(f'Browser version: {browser_session.version}')
			elif hasattr(browser_session, 'playwright_browser') and browser_session.playwright_browser:
				version = browser_session.playwright_browser.version
				logger.info(f'Browser version: {version}')
		except Exception as e:
			logger.debug(f'Could not determine browser version: {e}')
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

		# Configure logging for Textual UI before going fullscreen
		setup_textual_logging()

		# Log browser and model configuration that will be used
		browser_type = 'Chromium'  # BrowserSession only supports Chromium
		model_name = config.get('model', {}).get('name', 'auto-detected')
		headless = config.get('browser', {}).get('headless', True)
		headless_str = 'headless' if headless else 'visible'

		logger.info(f'Preparing {browser_type} browser ({headless_str}) with {model_name} LLM')

		logger.debug('Starting Textual app with run_async()...')
		# No more logging after this point as we're in fullscreen mode
		await app.run_async()
	except Exception as e:
		logger.error(f'Error in textual_interface: {str(e)}', exc_info=True)
		# Make sure to close browser session if app initialization fails
		if 'browser_session' in locals():
			await browser_session.close()
		raise


@click.command()
@click.option('--version', is_flag=True, help='Print version and exit')
@click.option('--model', type=str, help='Model to use (e.g., gpt-4o, claude-3-opus-20240229, gemini-pro)')
@click.option('--debug', is_flag=True, help='Enable verbose startup logging')
@click.option('--headless', is_flag=True, help='Run browser in headless mode', default=None)
@click.option('--window-width', type=int, help='Browser window width')
@click.option('--window-height', type=int, help='Browser window height')
@click.option(
	'--user-data-dir', type=str, help='Path to Chrome user data directory (e.g., ~/Library/Application Support/Google/Chrome)'
)
@click.option('--profile-directory', type=str, help='Chrome profile directory name (e.g., "Default", "Profile 1")')
@click.option('--cdp-url', type=str, help='Connect to existing Chrome via CDP URL (e.g., http://localhost:9222)')
@click.option('-p', '--prompt', type=str, help='Run a single task without the TUI (headless mode)')
@click.pass_context
def main(ctx: click.Context, debug: bool = False, **kwargs):
	"""Browser-Use Interactive TUI or Command Line Executor

	Use --user-data-dir to specify a local Chrome profile directory.
	Common Chrome profile locations:
	  macOS: ~/Library/Application Support/Google/Chrome
	  Linux: ~/.config/google-chrome
	  Windows: %LOCALAPPDATA%\\Google\\Chrome\\User Data

	Use --profile-directory to specify which profile within the user data directory.
	Examples: "Default", "Profile 1", "Profile 2", etc.
	"""

	if kwargs['version']:
		from importlib.metadata import version

		print(version('browser-use'))
		sys.exit(0)

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
		logger.debug(f'User configuration loaded from {USER_CONFIG_FILE}')
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
	headless = config.get('browser', {}).get('headless', True)
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


if __name__ == '__main__':
	main()
