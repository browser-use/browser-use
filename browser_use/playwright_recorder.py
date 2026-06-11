"""
Playwright Script Recorder for Browser-Use.

Records agent actions as a native Playwright Python script by attaching
``playwright codegen`` to the same Chrome instance that browser-use controls.

Usage::

    from browser_use import Agent, ChatBrowserUse
    from browser_use.playwright_recorder import record_playwright_script

    async with record_playwright_script('my_script.py') as browser_session:
        agent = Agent(task='...', llm=ChatBrowserUse(), browser_session=browser_session)
        await agent.run()

    # my_script.py now contains the recorded Playwright test script.

How it works:
  1. Detect Playwright's managed Chromium binary path at runtime.
  2. Temporarily replace that binary with a tiny shell-script wrapper that
     injects ``--remote-debugging-port=<port>`` into every Chrome launch.
  3. Start ``playwright codegen`` as a background process. Codegen launches
     Chrome via the wrapper, activating its built-in action recorder.
  4. Wait until Chrome exposes the CDP endpoint on that port.
  5. Connect a ``BrowserSession`` to that same Chrome tab via CDP, then yield
     it so the caller can wire it into their ``Agent``.
  6. After the caller's ``async with`` block exits (or raises), send SIGINT to
     codegen so it flushes the ``--output`` file and exits cleanly.
  7. Restore the original Chromium binary unconditionally (``finally``).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from browser_use.browser import BrowserSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
	"""Return a free TCP port on localhost by briefly binding to port 0."""
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
		sock.bind(('127.0.0.1', 0))
		return sock.getsockname()[1]


async def _get_chromium_path() -> Path:
	"""Detect the Playwright-managed Chromium executable path at runtime.

	Raises:
	    RuntimeError: if Playwright cannot find Chromium.
	    FileNotFoundError: if the detected path does not exist on disk.
	"""
	from playwright.async_api import async_playwright  # type: ignore[import-not-found]

	async with async_playwright() as p:
		path = p.chromium.executable_path

	if not path:
		raise RuntimeError('Playwright could not find a Chromium executable. Run: playwright install chromium')
	resolved = Path(path)
	if not resolved.exists():
		raise FileNotFoundError(f'Chromium binary not found at: {resolved}')
	return resolved


@contextlib.contextmanager
def _chrome_wrapper(chromium_path: Path, cdp_port: int):
	"""Context manager that temporarily replaces the Chromium binary.

	The replacement is a tiny shell script (or .bat on Windows) that forwards
	every argument to the real binary *plus* ``--remote-debugging-port=<port>``.
	The original binary is always restored in the ``finally`` block, even when
	the caller's code raises an exception.

	Args:
	    chromium_path: Absolute path to the Playwright Chromium executable.
	    cdp_port: The CDP port to inject into every Chrome launch.
	"""
	backup_path = chromium_path.parent / '_chrome_backup_browser_use'

	# Build a platform-appropriate wrapper script
	if platform.system() == 'Windows':
		wrapper_content = f'@echo off\n"{backup_path}" --remote-debugging-port={cdp_port} %*\n'
		wrapper_encoding = 'cp1252'
	else:
		wrapper_content = f'#!/bin/bash\nexec "{backup_path}" --remote-debugging-port={cdp_port} "$@"\n'
		wrapper_encoding = 'utf-8'

	shutil.copy2(chromium_path, backup_path)
	logger.debug(f'Chrome wrapper: backed up original binary → {backup_path}')

	try:
		chromium_path.write_text(wrapper_content, encoding=wrapper_encoding)
		chromium_path.chmod(0o755)
		logger.debug(f'Chrome wrapper installed → CDP port {cdp_port}')
		yield
	finally:
		shutil.copy2(backup_path, chromium_path)
		backup_path.unlink(missing_ok=True)
		logger.debug('Chrome wrapper removed, original binary restored')


def _wait_for_cdp(cdp_url: str, timeout: int = 30) -> bool:
	"""Poll the CDP /json/version endpoint until Chrome is ready.

	Args:
	    cdp_url: Base CDP URL, e.g. ``http://127.0.0.1:9223``.
	    timeout: Maximum seconds to wait before giving up.

	Returns:
	    ``True`` if the endpoint responded, ``False`` on timeout.
	"""
	deadline = time.monotonic() + timeout
	version_url = f'{cdp_url}/json/version'
	while time.monotonic() < deadline:
		try:
			urllib.request.urlopen(version_url, timeout=1)
			return True
		except Exception:
			time.sleep(0.4)
	return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@asynccontextmanager
async def record_playwright_script(
	output_path: str | Path,
	*,
	start_url: str = 'about:blank',
	target: str = 'python-async',
	cdp_port: int | None = None,
	cdp_timeout: int = 30,
	**browser_session_kwargs,
) -> AsyncGenerator[BrowserSession]:
	"""Async context manager that records agent actions as a Playwright script.

	Wraps any browser-use ``Agent`` run and produces a native Playwright
	Python (or other language) script capturing every browser interaction.

	Args:
	    output_path:
	        File path where the generated Playwright script will be written.
	        Parent directories are created automatically. The file is written
	        when the context manager exits (via ``playwright codegen``'s
	        ``--output`` flag).
	    start_url:
	        URL for ``playwright codegen`` to open when Chrome launches.
	        Defaults to ``about:blank``; the agent will navigate from there.
	    target:
	        Playwright codegen language target. Common choices:

	        * ``"python-async"`` *(default)* — ``async`` Playwright Python
	        * ``"python"`` — synchronous Playwright Python
	        * ``"javascript"`` — Playwright for Node.js
	        * ``"java"`` — Playwright for Java
	        * ``"csharp"`` — Playwright for C#

	    cdp_port:
	        TCP port for the Chrome DevTools Protocol endpoint. If ``None``
	        (default), an available ephemeral port is chosen automatically.
	    cdp_timeout:
	        Seconds to wait for Chrome to expose its CDP endpoint before
	        raising a ``RuntimeError``.
	    **browser_session_kwargs:
	        Additional keyword arguments to pass to the ``BrowserSession``
	        constructor (e.g., ``record_video_dir``).

	Yields:
	    A ``BrowserSession`` already connected to the codegen-managed Chrome
	    instance. Pass this directly to ``Agent(browser_session=...)``.

	Raises:
	    RuntimeError: if Chromium is not found or CDP does not become ready.
	    FileNotFoundError: if the Chromium binary cannot be located on disk.

	Example::

	    from browser_use import Agent, ChatBrowserUse
	    from browser_use.playwright_recorder import record_playwright_script


	    async def main():
	        async with record_playwright_script('recorded.py') as browser_session:
	            agent = Agent(
	                task='Go to github.com and find the trending repos',
	                llm=ChatBrowserUse(),
	                browser_session=browser_session,
	            )
	            await agent.run()
	        print('Script saved to recorded.py')
	"""
	# Resolve output path early so errors surface before Chrome launches
	output_path = Path(output_path).resolve()
	output_path.parent.mkdir(parents=True, exist_ok=True)

	port = cdp_port if cdp_port is not None else _find_free_port()
	cdp_url = f'http://127.0.0.1:{port}'

	chromium_path = await _get_chromium_path()
	logger.info(f'🎬 Playwright recorder: Chromium at {chromium_path}, CDP port {port}')

	# Environment for the codegen subprocess:
	# PWDEBUG=0 suppresses the separate Playwright Inspector popup window so
	# only the recorder is active (not the interactive inspector UI).
	codegen_env = {**os.environ, 'PWDEBUG': '0'}

	codegen_cmd = [
		sys.executable,
		'-m',
		'playwright',
		'codegen',
		'--target',
		target,
		'--output',
		str(output_path),
		start_url,
	]

	codegen_proc: asyncio.subprocess.Process | None = None

	with _chrome_wrapper(chromium_path, port):
		try:
			logger.info('▶  Starting playwright codegen (recorder active)…')
			codegen_proc = await asyncio.create_subprocess_exec(
				*codegen_cmd,
				env=codegen_env,
				stdout=subprocess.DEVNULL,
				stderr=subprocess.DEVNULL,
			)

			logger.info(f'   Waiting for Chrome on {cdp_url}…')
			if not _wait_for_cdp(cdp_url, timeout=cdp_timeout):
				raise RuntimeError(
					f'Chrome did not expose a CDP endpoint on port {port} '
					f'within {cdp_timeout}s. '
					'Make sure playwright is installed: playwright install chromium'
				)
			logger.info(f'✅  Chrome ready on {cdp_url}')

			# Import lazily to avoid circular imports at module load time
			from browser_use.browser import BrowserSession  # type: ignore[import-not-found]

			# Merge user kwargs with our required args
			kwargs = {**browser_session_kwargs, 'cdp_url': cdp_url, 'keep_alive': True}
			browser_session = BrowserSession(**kwargs)

			yield browser_session

		finally:
			# ── Flush the generated script ────────────────────────────────
			if codegen_proc is not None and codegen_proc.returncode is None:
				logger.info('▶  Sending SIGINT to playwright codegen → flushing script…')
				try:
					if platform.system() == 'Windows':
						codegen_proc.send_signal(getattr(signal, 'CTRL_C_EVENT', signal.SIGINT))
					else:
						codegen_proc.send_signal(signal.SIGINT)
					await asyncio.wait_for(codegen_proc.wait(), timeout=10.0)
				except TimeoutError:
					logger.warning('codegen did not exit within 10 s — killing it')
					codegen_proc.kill()
					await codegen_proc.wait()
				except Exception as exc:
					logger.warning(f'Error stopping codegen process: {exc}')

			# ── Log result ────────────────────────────────────────────────
			if output_path.exists():
				size = output_path.stat().st_size
				logger.info(f'✅  Playwright script saved → {output_path} ({size} bytes)')
			else:
				logger.warning(
					f'⚠  Playwright script was NOT written to {output_path}. '
					'codegen may need the browser to be closed manually first.'
				)

	# Outside the _chrome_wrapper so binary is always restored before we return
