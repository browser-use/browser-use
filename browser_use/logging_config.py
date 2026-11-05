import logging
import os
import sys


def setup_logging(level: str | None = None) -> logging.Logger:
	"""One stderr handler on the 'browser_use' logger. BROWSER_USE_LOGGING_LEVEL=debug|info|warning|error."""
	level = (level or os.getenv('BROWSER_USE_LOGGING_LEVEL', 'info')).lower()
	logger = logging.getLogger('browser_use')
	if not logger.handlers:
		handler = logging.StreamHandler(sys.stderr)
		handler.setFormatter(logging.Formatter('%(levelname)-8s [%(name)s] %(message)s'))
		logger.addHandler(handler)
	logger.setLevel(getattr(logging, level.upper(), logging.INFO))
	logger.propagate = False
	return logger
