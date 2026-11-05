import logging
import os
from functools import cache
from importlib.metadata import PackageNotFoundError, version

logger = logging.getLogger(__name__)


def singleton(cls):
	instance = [None]

	def wrapper(*args, **kwargs):
		if instance[0] is None:
			instance[0] = cls(*args, **kwargs)
		return instance[0]

	return wrapper


@cache
def get_browser_use_version() -> str:
	try:
		return version('browser-use')
	except PackageNotFoundError:
		return 'unknown'


@cache
def get_install_source() -> str:
	"""'git' for a source checkout, 'pip' for an installed package (same rule as 0.x telemetry)."""
	root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	return 'git' if all(os.path.exists(os.path.join(root, f)) for f in ('.git', 'README.md', 'examples')) else 'pip'
