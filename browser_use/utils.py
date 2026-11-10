import http.client
import logging
import os
import ssl
import threading
import urllib.request
from collections.abc import Iterator
from functools import cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)
MAX_NAME_BYTES = 255  # a file name, on every common filesystem
FD_LIMIT = 10240  # ~3 fds per live Agent (model connection, REPL socket, worker pipe): thousands of concurrent Agents


class _NoRedirect(urllib.request.HTTPRedirectHandler):
	def redirect_request(self, *args: Any, **kwargs: Any) -> None:
		return None  # urllib then raises the 3xx as an HTTPError


def new_tls_context() -> ssl.SSLContext:
	"""The TLS context of every HTTPS request this package makes itself: it trusts what the OS trusts. Python's default
	context reads only the roots already in the Windows store, and a fresh Windows host fetches a missing root (the
	Starfield root behind api.browser-use.com) only when the OS verifier asks for it: urllib failed with
	CERTIFICATE_VERIFY_FAILED where Edge, curl.exe and the model calls (httpx2 uses truststore) worked. truststore verifies
	with the OS (Windows CryptoAPI, macOS Security, OpenSSL's system store on Linux); SSL_CERT_FILE and SSL_CERT_DIR are
	trusted too, as before. Without truststore: Python's default context plus certifi's roots."""
	try:
		import truststore

		ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
	except Exception as e:  # - not installed, or this platform's verifier cannot load
		logger.debug('truststore unavailable (%s): default TLS context with certifi', e)
	else:
		cafile, capath = os.environ.get('SSL_CERT_FILE') or None, os.environ.get('SSL_CERT_DIR') or None
		if cafile or capath:  # a proxy's CA: extra roots, as the default context loaded them
			try:
				ctx.load_verify_locations(cafile, capath)
			except (OSError, ssl.SSLError) as e:
				logger.debug('SSL_CERT_FILE / SSL_CERT_DIR not loaded: %s', e)
		return ctx
	ctx = ssl.create_default_context()
	try:
		import certifi

		ctx.load_verify_locations(certifi.where())
	except Exception as e:  # - certifi missing or unreadable: the default roots alone
		logger.debug('certifi unavailable: %s', e)
	return ctx


_thread_tls = threading.local()


def tls_context() -> ssl.SSLContext:
	"""This thread's new_tls_context(), made on its first call. truststore holds a context's lock through the whole
	handshake: with one context for every thread, a handshake that stalled (telemetry to a firewalled PostHog) held up the
	other threads' HTTPS, the gateway check included, until its timeout."""
	ctx = getattr(_thread_tls, 'ctx', None)
	if ctx is None:
		ctx = _thread_tls.ctx = new_tls_context()
	return ctx


class TLSHandler(urllib.request.HTTPSHandler):
	"""HTTPS through tls_context(), made on the first HTTPS request: loading it takes tens of ms, too long for every CLI call."""

	def https_open(self, req: urllib.request.Request) -> Any:
		return self.do_open(http.client.HTTPSConnection, req, context=tls_context())


class _TLSOpener:
	"""build_opener(TLSHandler), built on the first urlopen as urllib builds its default opener: proxy variables set by
	then (the .env browser-harness reads when it is imported) apply. Built at install, HTTPS_PROXY from that .env was ignored."""

	_opener: urllib.request.OpenerDirector | None = None

	def open(self, *args: Any, **kwargs: Any) -> Any:
		if self._opener is None:
			self._opener = urllib.request.build_opener(TLSHandler)
		return self._opener.open(*args, **kwargs)


def install_tls_opener() -> None:
	"""Send urllib.request.urlopen in this process through tls_context(): browser-harness's own requests (cloud browser
	start and stop, login, its version check) and piped code. Only in processes this package runs (the CLI, the MCP
	server, the REPL worker), never on import: a library must not change urllib for the program that imports it."""
	urllib.request.install_opener(_TLSOpener())  # type: ignore[arg-type]  # urlopen only calls .open


_keyed_opener = urllib.request.build_opener(_NoRedirect, TLSHandler)


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


def file_names(dest: Path, name: str) -> Iterator[Path]:
	"""Paths in dest for a file called name: 'report.csv', then 'report (1).csv', 'report (2).csv', ... A long name is
	shortened, never dropped."""
	stem, suffix = Path(name).stem, Path(name).suffix
	if len(suffix.encode()) > 32:  # not an extension: part of a long name
		stem, suffix = name, ''
	for i in range(10_000):
		tail = suffix if i == 0 else f' ({i}){suffix}'
		room = MAX_NAME_BYTES - len(tail.encode())
		yield dest / (stem.encode()[:room].decode(errors='ignore') + tail)


def name_download(path: Path, name: str | None) -> Path | None:
	"""Give a download Chrome saved as <dir>/<guid> (Browser.setDownloadBehavior allowAndName) its suggested name, never
	over another file: a repeated name is 'invoice (1).txt', as cloud copies are named. With behavior 'allow' Chrome
	wrote a second invoice.txt over the first. Returns the new path; None when path is gone (already named)."""
	base = Path(str(name or '')).name.strip()
	if base in ('', '.', '..', path.name):  # no name to give: it keeps its guid
		return path if path.exists() else None
	for dest in file_names(path.parent, base):
		try:
			os.link(path, dest)  # - fails if dest exists: never overwrites, even when two names are taken at once
		except FileExistsError:
			continue
		except FileNotFoundError:
			return None
		except OSError:  # a filesystem without hard links: claim dest atomically, then move over the claim
			try:
				os.close(os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
			except FileExistsError:  # an exists() check let two downloads take one name, the second replacing the first
				continue
			try:
				os.replace(path, dest)
			except OSError as e:
				dest.unlink(missing_ok=True)
				if isinstance(e, FileNotFoundError):
					return None
				raise
			return dest
		path.unlink(missing_ok=True)
		return dest
	return None


if not TYPE_CHECKING:  # pyright would accept any name imported from here
	from browser_use.legacy import removed_names

	__getattr__ = removed_names(__name__)  # a 0.x name raises the removed error naming its 1.0 answer
