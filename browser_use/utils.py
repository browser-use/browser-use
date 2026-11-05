import logging
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
	"""How browser-use is installed: 'editable' (pip install -e / uv sync of a checkout), 'git' (from a VCS URL), else
	the installer that wrote the package ('pip', 'uv', ...), or 'unknown'. Read from the package metadata, so it does not
	depend on where the checkout or its repository root is."""
	import json
	from importlib.metadata import distribution

	try:
		dist = distribution('browser-use')
		direct = json.loads(dist.read_text('direct_url.json') or '{}')
		if direct.get('dir_info', {}).get('editable'):
			return 'editable'
		if 'vcs_info' in direct:
			return 'git'
		return (dist.read_text('INSTALLER') or '').strip().lower()[:20] or 'unknown'
	except Exception:
		return 'unknown'
