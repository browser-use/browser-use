"""Shared fixtures. Nothing here calls a model provider or Browser Use Cloud."""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import warnings
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

os.environ['ANONYMIZED_TELEMETRY'] = 'false'
os.environ['BH_TAB_MARKER'] = '0'
# REPL workers without an explicit daemon must fail, never drive the developer's own Chrome (the default daemon).
os.environ['BU_NAME'] = 'browser-use-tests-no-daemon'
# The Browser Use key store (`browser-use login`) points at a file that never exists: no test reads the developer's key.
os.environ['BH_AUTH_PATH'] = str(Path(tempfile.gettempdir()) / 'browser-use-tests-no-auth' / 'auth.json')
# The 0.x config.json `browser-use --mcp` reads: never the developer's own.
os.environ['BROWSER_USE_CONFIG_DIR'] = str(Path(tempfile.gettempdir()) / 'browser-use-tests-no-config')
os.environ['BROWSER_USE_TELEMETRY_INTERNAL'] = '1'

# No test reaches the real PostHog: a test that points telemetry at a dead host left a send in flight, and its retry went
# to the module's host once the fixture had restored it (an event from bu-test-device in production per suite run).
import browser_use.telemetry.service as _telemetry_service  # noqa: E402

_telemetry_service.POSTHOG_HOST = 'http://127.0.0.1:9'  # nothing listens on port 9


def find_chrome() -> str | None:
	candidates = [
		os.environ.get('CHROME'),
		'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		r'C:\Program Files\Google\Chrome\Application\chrome.exe',
		*(shutil.which(n) for n in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome')),
	]
	return next((c for c in candidates if c and Path(c).exists()), None)


@pytest.fixture
def chrome_binary() -> str:
	"""The Chrome binary, for tests where Browser launches its own (Browser('chromium'), Browser('chrome', profile=))."""
	return find_chrome() or pytest.skip('Chrome not installed')


@pytest.fixture(scope='module')
def chrome():
	"""An isolated headless Chrome: {'http': devtools http url, 'ws': browser websocket url}."""
	binary = find_chrome()
	if not binary:
		pytest.skip('Chrome not installed')
	with socket.socket() as s:
		s.bind(('127.0.0.1', 0))
		port = s.getsockname()[1]
	profile = tempfile.mkdtemp()
	args = [binary, '--headless=new', f'--remote-debugging-port={port}', f'--user-data-dir={profile}', '--no-first-run']
	if sys.platform.startswith('linux'):
		args.append('--no-sandbox')
	proc = subprocess.Popen([*args, 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
	ws = None
	for _ in range(150):
		try:
			ws = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version'))['webSocketDebuggerUrl']
			break
		except OSError:
			time.sleep(0.1)
	if ws is None:
		proc.kill()
		proc.wait()
		pytest.skip('Chrome did not start')
	yield {'http': f'http://127.0.0.1:{port}', 'ws': ws}
	proc.kill()
	proc.wait()  # reaped before its profile is removed
	shutil.rmtree(profile, ignore_errors=True)


@pytest.fixture(scope='module')
def daemon(chrome):
	"""A named browser-harness daemon on the isolated Chrome; the REPL env that drives it."""
	from browser_harness import admin

	name = f'butest{os.getpid()}{chrome["http"].rsplit(":", 1)[1]}'
	admin.ensure_daemon(name=name, env={'BU_CDP_WS': chrome['ws']})
	yield {'BU_NAME': name}
	try:
		admin.restart_daemon(name)
	except Exception as e:  # a daemon left running shows in the test output
		warnings.warn(f'browser-harness daemon {name} did not stop: {e!r}', stacklevel=1)


@pytest.fixture
def shared_runtime_dir(monkeypatch):
	"""browser-harness's runtime dir as another user's pre-created /tmp/bh looks (0777; short: AF_UNIX paths are)."""
	from browser_harness import _ipc as ipc

	if sys.platform == 'win32':
		pytest.skip('Windows uses token-gated TCP loopback')
	path = Path(tempfile.mkdtemp(prefix='bh', dir='/tmp'))
	path.chmod(0o777)
	monkeypatch.setattr(ipc, '_RUNTIME', path)
	yield path
	shutil.rmtree(path, ignore_errors=True)


def script(*turns):
	"""FunctionModel playing tool calls in order. Each turn: (tool, args) or a list of them. Records requests."""
	seen = []

	def fn(messages, info: AgentInfo):
		seen.append(messages)
		if len(seen) > len(turns):
			raise AssertionError(f'unexpected model call {len(seen)}; last {messages[-1]!r}'[:4000])
		turn = turns[len(seen) - 1]
		calls = turn if isinstance(turn, list) else [turn]
		return ModelResponse(parts=[ToolCallPart(name, args) for name, args in calls])

	return FunctionModel(fn), seen


def pytest_collection_modifyitems(items):
	for item in items:  # `-m "not chrome"` runs everything that needs no browser (the Windows/macOS/Linux matrix)
		if {'chrome', 'daemon', 'chrome_binary'} & set(getattr(item, 'fixturenames', ())):
			item.add_marker(pytest.mark.chrome)
