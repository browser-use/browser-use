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
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

os.environ['ANONYMIZED_TELEMETRY'] = 'false'
os.environ['BH_TAB_MARKER'] = '0'


def find_chrome() -> str | None:
	candidates = [
		os.environ.get('CHROME'),
		'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		r'C:\Program Files\Google\Chrome\Application\chrome.exe',
		*(shutil.which(n) for n in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome')),
	]
	return next((c for c in candidates if c and Path(c).exists()), None)


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
		pytest.skip('Chrome did not start')
	yield {'http': f'http://127.0.0.1:{port}', 'ws': ws}
	proc.kill()
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
	except Exception:
		pass


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
		if {'chrome', 'daemon'} & set(getattr(item, 'fixturenames', ())):
			item.add_marker(pytest.mark.chrome)
