import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from browser_use.config import CONFIG


def addLoggingLevel(levelName, levelNum, methodName=None):
	"""
	Comprehensively adds a new logging level to the `logging` module and the
	currently configured logging class.

	`levelName` becomes an attribute of the `logging` module with the value
	`levelNum`. `methodName` becomes a convenience method for both `logging`
	itself and the class returned by `logging.getLoggerClass()` (usually just
	`logging.Logger`). If `methodName` is not specified, `levelName.lower()` is
	used.

	To avoid accidental clobberings of existing attributes, this method will
	raise an `AttributeError` if the level name is already an attribute of the
	`logging` module or if the method name is already present

	Example
	-------
	>>> addLoggingLevel('TRACE', logging.DEBUG - 5)
	>>> logging.getLogger(__name__).setLevel('TRACE')
	>>> logging.getLogger(__name__).trace('that worked')
	>>> logging.trace('so did this')
	>>> logging.TRACE
	5

	"""
	if not methodName:
		methodName = levelName.lower()

	if hasattr(logging, levelName):
		raise AttributeError(f'{levelName} already defined in logging module')
	if hasattr(logging, methodName):
		raise AttributeError(f'{methodName} already defined in logging module')
	if hasattr(logging.getLoggerClass(), methodName):
		raise AttributeError(f'{methodName} already defined in logger class')

	# This method was inspired by the answers to Stack Overflow post
	# http://stackoverflow.com/q/2183233/2988730, especially
	# http://stackoverflow.com/a/13638084/2988730
	def logForLevel(self, message, *args, **kwargs):
		if self.isEnabledFor(levelNum):
			self._log(levelNum, message, args, **kwargs)

	def logToRoot(message, *args, **kwargs):
		logging.log(levelNum, message, *args, **kwargs)

	logging.addLevelName(levelNum, levelName)
	setattr(logging, levelName, levelNum)
	setattr(logging.getLoggerClass(), methodName, logForLevel)
	setattr(logging, methodName, logToRoot)


def setup_logging(stream=None, log_level=None, force_setup=False):
	"""Setup logging configuration for browser-use.

	Args:
		stream: Output stream for logs (default: sys.stdout). Can be sys.stderr for MCP mode.
		log_level: Override log level (default: uses CONFIG.BROWSER_USE_LOGGING_LEVEL)
		force_setup: Force reconfiguration even if handlers already exist
	"""
	# Try to add RESULT level, but ignore if it already exists
	try:
		addLoggingLevel('RESULT', 35)  # This allows ERROR, FATAL and CRITICAL
	except AttributeError:
		pass  # Level already exists, which is fine

	log_type = log_level or CONFIG.BROWSER_USE_LOGGING_LEVEL

	# Check if handlers are already set up
	if logging.getLogger().hasHandlers() and not force_setup:
		return logging.getLogger('browser_use')

	# Clear existing handlers
	root = logging.getLogger()
	root.handlers = []

	class BrowserUseFormatter(logging.Formatter):
		def format(self, record):
			# if isinstance(record.name, str) and record.name.startswith('browser_use.'):
			# 	record.name = record.name.split('.')[-2]
			return super().format(record)

	# Setup single handler for all loggers
	console = logging.StreamHandler(stream or sys.stdout)

	# adittional setLevel here to filter logs
	if log_type == 'result':
		console.setLevel('RESULT')
		console.setFormatter(BrowserUseFormatter('%(message)s'))
	else:
		console.setFormatter(BrowserUseFormatter('%(levelname)-8s [%(name)s] %(message)s'))

	# Configure root logger only
	root.addHandler(console)

	# Determine the log level to use
	if log_type == 'result':
		log_level = 35  # RESULT level value
	elif log_type == 'debug':
		log_level = logging.DEBUG
	else:
		log_level = logging.INFO

	# Configure root logger
	root.setLevel(log_level)

	# Configure browser_use logger
	browser_use_logger = logging.getLogger('browser_use')
	browser_use_logger.propagate = False  # Don't propagate to root logger
	browser_use_logger.addHandler(console)
	browser_use_logger.setLevel(log_level)

	# Configure bubus logger to allow INFO level logs
	bubus_logger = logging.getLogger('bubus')
	bubus_logger.propagate = False  # Don't propagate to root logger
	bubus_logger.addHandler(console)
	bubus_logger.setLevel(logging.INFO if log_type == 'result' else log_level)

	# Configure CDP logging using cdp_use's setup function
	# This enables the formatted CDP output at the same level as browser_use
	try:
		from cdp_use.logging import setup_cdp_logging  # type: ignore

		# Use the same stream and level as browser_use
		setup_cdp_logging(
			level=log_level,
			stream=stream or sys.stdout,
			format_string='%(levelname)-8s [%(name)s] %(message)s' if log_type != 'result' else '%(message)s',
		)
	except ImportError:
		# If cdp_use doesn't have the new logging module, fall back to manual config
		cdp_loggers = [
			'websockets.client',
			'cdp_use',
			'cdp_use.client',
			'cdp_use.cdp',
			'cdp_use.cdp.registry',
		]
		for logger_name in cdp_loggers:
			cdp_logger = logging.getLogger(logger_name)
			cdp_logger.setLevel(log_level)
			cdp_logger.addHandler(console)
			cdp_logger.propagate = False

	logger = logging.getLogger('browser_use')
	# logger.info('BrowserUse logging setup complete with level %s', log_type)

	# Silence third-party loggers (but not CDP ones which we configured above)
	third_party_loggers = [
		'WDM',
		'httpx',
		'selenium',
		'playwright',
		'urllib3',
		'asyncio',
		'langsmith',
		'langsmith.client',
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
		'websockets',  # General websockets (but not websockets.client which we need)
	]
	for logger_name in third_party_loggers:
		third_party = logging.getLogger(logger_name)
		third_party.setLevel(logging.ERROR)
		third_party.propagate = False

	return logger


class FIFOHandler(logging.Handler):
	"""Non-blocking handler that writes to a named pipe."""

	def __init__(self, fifo_path: str):
		super().__init__()
		self.fifo_path = fifo_path
		Path(fifo_path).parent.mkdir(parents=True, exist_ok=True)

		# Create FIFO if it doesn't exist
		if not os.path.exists(fifo_path):
			os.mkfifo(fifo_path)

		# Don't open the FIFO yet - will open on first write
		self.fd = None

	def emit(self, record):
		try:
			# Open FIFO on first write if not already open
			if self.fd is None:
				try:
					self.fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
				except OSError:
					# No reader connected yet, skip this message
					return

			msg = f'{self.format(record)}\n'.encode()
			os.write(self.fd, msg)
		except (OSError, BrokenPipeError):
			# Reader disconnected, close and reset
			if self.fd is not None:
				try:
					os.close(self.fd)
				except Exception:
					pass
				self.fd = None

	def close(self):
		if hasattr(self, 'fd') and self.fd is not None:
			try:
				os.close(self.fd)
			except Exception:
				pass
		super().close()


def setup_log_pipes(session_id: str, base_dir: str | None = None):
	"""Setup named pipes for log streaming.

	Usage:
		# In browser-use:
		setup_log_pipes(session_id="abc123")

		# In consumer process:
		tail -f {temp_dir}/buagent.c123/agent.pipe
	"""
	import tempfile

	if base_dir is None:
		base_dir = tempfile.gettempdir()

	suffix = session_id[-4:]
	pipe_dir = Path(base_dir) / f'buagent.{suffix}'

	# Agent logs
	agent_handler = FIFOHandler(str(pipe_dir / 'agent.pipe'))
	agent_handler.setLevel(logging.DEBUG)
	agent_handler.setFormatter(logging.Formatter('%(levelname)-8s [%(name)s] %(message)s'))
	for name in ['browser_use.agent', 'browser_use.controller']:
		logger = logging.getLogger(name)
		logger.addHandler(agent_handler)
		logger.setLevel(logging.DEBUG)
		logger.propagate = True

	# CDP logs
	cdp_handler = FIFOHandler(str(pipe_dir / 'cdp.pipe'))
	cdp_handler.setLevel(logging.DEBUG)
	cdp_handler.setFormatter(logging.Formatter('%(levelname)-8s [%(name)s] %(message)s'))
	for name in ['websockets.client', 'cdp_use.client']:
		logger = logging.getLogger(name)
		logger.addHandler(cdp_handler)
		logger.setLevel(logging.DEBUG)
		logger.propagate = True

	# Event logs
	event_handler = FIFOHandler(str(pipe_dir / 'events.pipe'))
	event_handler.setLevel(logging.INFO)
	event_handler.setFormatter(logging.Formatter('%(levelname)-8s [%(name)s] %(message)s'))
	for name in ['bubus', 'browser_use.browser.session']:
		logger = logging.getLogger(name)
		logger.addHandler(event_handler)
		logger.setLevel(logging.INFO)  # Enable INFO for event bus
		logger.propagate = True
