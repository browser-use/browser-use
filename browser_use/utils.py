import logging
import urllib.request
from functools import cache
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)
FD_LIMIT = 10240  # ~3 fds per live Agent (model connection, REPL socket, worker pipe): thousands of concurrent Agents


class _NoRedirect(urllib.request.HTTPRedirectHandler):
	def redirect_request(self, *args: Any, **kwargs: Any) -> None:
		return None  # urllib then raises the 3xx as an HTTPError


_keyed_opener = urllib.request.build_opener(_NoRedirect)


def urlopen_keyed(request: urllib.request.Request, timeout: float) -> Any:
	"""urlopen for a request that carries an API key. It never follows a redirect: urllib copies every header to the new
	URL, so a redirect to another origin would hand it the key. A 3xx raises HTTPError, as httpx does for the model calls."""
	return _keyed_opener.open(request, timeout=timeout)


def raise_fd_limit() -> None:
	"""Raise the soft open-file limit toward the hard one (no privileges needed). macOS starts processes at 256, and
	100 concurrent Agents in one process use ~300: connects and binds failed with EMFILE, DNS failed (a model call then
	read 'Connection error.'). Never lowers a limit; a no-op on Windows."""
	try:
		import resource
	except ImportError:
		return
	soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
	want = FD_LIMIT if hard == resource.RLIM_INFINITY else min(hard, FD_LIMIT)
	if soft != resource.RLIM_INFINITY and soft < want:
		try:
			resource.setrlimit(resource.RLIMIT_NOFILE, (want, hard))
		except (ValueError, OSError) as e:
			logger.debug(f'Could not raise the open-file limit from {soft} to {want}: {e}')


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


if not TYPE_CHECKING:  # pyright would accept any name imported from here
	from browser_use.legacy import removed_names

	__getattr__ = removed_names(__name__)  # a 0.x name raises the removed error naming its 1.0 answer
