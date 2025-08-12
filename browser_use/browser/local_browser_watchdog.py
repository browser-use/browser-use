"""Local browser watchdog for managing browser subprocess lifecycle."""

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import psutil
from bubus import BaseEvent
from pydantic import PrivateAttr

from browser_use.browser.events import (
	BrowserKillEvent,
	BrowserLaunchEvent,
	BrowserStopEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog

if TYPE_CHECKING:
	pass


class LocalBrowserWatchdog(BaseWatchdog):
	"""Manages local browser subprocess lifecycle."""

	# Events this watchdog listens to
	LISTENS_TO: ClassVar[list[type[BaseEvent[Any]]]] = [
		BrowserLaunchEvent,
		BrowserKillEvent,
		BrowserStopEvent,
	]

	# Events this watchdog emits
	EMITS: ClassVar[list[type[BaseEvent[Any]]]] = []

	# Private state for subprocess management
	_subprocess: psutil.Process | None = PrivateAttr(default=None)
	_owns_browser_resources: bool = PrivateAttr(default=True)
	_temp_dirs_to_cleanup: list[Path] = PrivateAttr(default_factory=list)
	_original_user_data_dir: str | None = PrivateAttr(default=None)

	async def on_BrowserLaunchEvent(self, event: BrowserLaunchEvent) -> dict[str, str]:
		"""Launch a local browser process."""
		try:
			self.logger.info(
				f'[LocalBrowserWatchdog] Received BrowserLaunchEvent, EventBus ID: {id(self.event_bus)}, launching local browser'
			)

			self.logger.debug('[LocalBrowserWatchdog] Calling _launch_browser...')
			process, cdp_url = await self._launch_browser()
			self.logger.debug(f'[LocalBrowserWatchdog] _launch_browser returned: process={process}, cdp_url={cdp_url}')

			self._subprocess = process

			self.logger.info(f'[LocalBrowserWatchdog] Browser launched successfully at {cdp_url}, PID: {process.pid}')
			return {'cdp_url': cdp_url}
		except Exception as e:
			self.logger.error(f'[LocalBrowserWatchdog] Exception in on_BrowserLaunchEvent: {e}', exc_info=True)
			raise

	async def on_BrowserKillEvent(self, event: BrowserKillEvent) -> None:
		"""Kill the local browser subprocess."""
		self.logger.info('[LocalBrowserWatchdog] Killing local browser process')

		if self._subprocess:
			await self._cleanup_process(self._subprocess)
			self._subprocess = None

		# Clean up temp directories if any were created
		for temp_dir in self._temp_dirs_to_cleanup:
			self._cleanup_temp_dir(temp_dir)
		self._temp_dirs_to_cleanup.clear()

		# Restore original user_data_dir if it was modified
		if self._original_user_data_dir is not None:
			self.browser_session.browser_profile.user_data_dir = self._original_user_data_dir
			self._original_user_data_dir = None

		self.logger.info('[LocalBrowserWatchdog] Browser cleanup completed')

	async def on_BrowserStopEvent(self, event: BrowserStopEvent) -> None:
		"""Listen for BrowserStopEvent and dispatch BrowserKillEvent without awaiting it."""
		if self.browser_session.is_local and self._subprocess:
			self.logger.info('[LocalBrowserWatchdog] BrowserStopEvent received, dispatching BrowserKillEvent')
			# Dispatch BrowserKillEvent without awaiting so it gets processed after all BrowserStopEvent handlers
			self.event_bus.dispatch(BrowserKillEvent())

	async def _launch_browser(self, max_retries: int = 3) -> tuple[psutil.Process, str]:
		"""Launch browser process and return (process, cdp_url).

		Handles launch errors by falling back to temporary directories if needed.

		Returns:
			Tuple of (psutil.Process, cdp_url)
		"""
		# Keep track of original user_data_dir to restore if needed
		profile = self.browser_session.browser_profile
		self._original_user_data_dir = str(profile.user_data_dir) if profile.user_data_dir else None
		self._temp_dirs_to_cleanup = []

		for attempt in range(max_retries):
			try:
				# Get launch args from profile
				launch_args = profile.get_args()

				# Add debugging port
				debug_port = self._find_free_port()
				launch_args.extend(
					[
						f'--remote-debugging-port={debug_port}',
					]
				)

				# Get browser executable from playwright
				# Use custom executable if provided, otherwise use playwright's
				if profile.executable_path:
					browser_path = profile.executable_path
					self.logger.debug(f'[LocalBrowserWatchdog] Using custom executable: {browser_path}')
				else:
					self.logger.debug('[LocalBrowserWatchdog] Getting browser path from playwright...')
					# Get browser path from playwright in a subprocess to avoid thread issues
					browser_path = await self._get_browser_path_via_subprocess()
					self.logger.debug(f'[LocalBrowserWatchdog] Got browser path: {browser_path}')

				# Launch browser subprocess directly
				self.logger.debug(f'[LocalBrowserWatchdog] Launching browser subprocess with {len(launch_args)} args...')
				subprocess = await asyncio.create_subprocess_exec(
					browser_path,
					*launch_args,
					stdout=asyncio.subprocess.PIPE,
					stderr=asyncio.subprocess.PIPE,
				)
				self.logger.debug(f'[LocalBrowserWatchdog] Browser subprocess launched with PID: {subprocess.pid}')

				# Convert to psutil.Process
				process = psutil.Process(subprocess.pid)

				# Wait for CDP to be ready and get the URL
				cdp_url = await self._wait_for_cdp_url(debug_port)

				# Success! Clean up any temp dirs we created but didn't use
				for tmp_dir in self._temp_dirs_to_cleanup:
					try:
						shutil.rmtree(tmp_dir, ignore_errors=True)
					except Exception:
						pass

				return process, cdp_url

			except Exception as e:
				error_str = str(e).lower()

				# Check if this is a user_data_dir related error
				if any(err in error_str for err in ['singletonlock', 'user data directory', 'cannot create', 'already in use']):
					self.logger.warning(f'Browser launch failed (attempt {attempt + 1}/{max_retries}): {e}')

					if attempt < max_retries - 1:
						# Create a temporary directory for next attempt
						tmp_dir = Path(tempfile.mkdtemp(prefix='browseruse-tmp-'))
						self._temp_dirs_to_cleanup.append(tmp_dir)

						# Update profile to use temp directory
						profile.user_data_dir = str(tmp_dir)
						self.logger.info(f'Retrying with temporary user_data_dir: {tmp_dir}')

						# Small delay before retry
						await asyncio.sleep(0.5)
						continue

				# Not a recoverable error or last attempt failed
				# Restore original user_data_dir before raising
				if self._original_user_data_dir is not None:
					profile.user_data_dir = self._original_user_data_dir

				# Clean up any temp dirs we created
				for tmp_dir in self._temp_dirs_to_cleanup:
					try:
						shutil.rmtree(tmp_dir, ignore_errors=True)
					except Exception:
						pass

				raise

		# Should not reach here, but just in case
		if self._original_user_data_dir is not None:
			profile.user_data_dir = self._original_user_data_dir
		raise RuntimeError(f'Failed to launch browser after {max_retries} attempts')

	@staticmethod
	async def _get_browser_path_via_subprocess() -> str:
		"""Get browser executable path from playwright in a subprocess to avoid thread issues."""
		import json
		import sys

		# Python code to run in subprocess
		get_path_code = """
import asyncio
import json
import sys

async def get_path():
    from playwright.async_api import async_playwright
    playwright = await async_playwright().start()
    try:
        path = playwright.chromium.executable_path
        print(json.dumps({"path": path}))
    finally:
        await playwright.stop()

asyncio.run(get_path())
"""

		# Run in subprocess with timeout
		process = await asyncio.create_subprocess_exec(
			sys.executable,
			'-c',
			get_path_code,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE,
		)

		try:
			# Wait for result with timeout
			stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10.0)

			# Parse the result
			if stdout:
				result = json.loads(stdout.decode())
				return result['path']
			else:
				# Fallback to default location if subprocess fails
				error_msg = stderr.decode() if stderr else 'Unknown error'
				raise RuntimeError(f'Failed to get browser path from playwright: {error_msg}')

		except TimeoutError:
			# Kill the subprocess if it times out
			process.kill()
			await process.wait()
			raise RuntimeError('Timeout getting browser path from playwright')
		except Exception as e:
			# Make sure subprocess is terminated
			if process.returncode is None:
				process.kill()
				await process.wait()
			raise RuntimeError(f'Error getting browser path: {e}')

	@staticmethod
	def _find_free_port() -> int:
		"""Find a free port for the debugging interface."""
		import socket

		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
			s.bind(('127.0.0.1', 0))
			s.listen(1)
			port = s.getsockname()[1]
		return port

	@staticmethod
	async def _wait_for_cdp_url(port: int, timeout: float = 30) -> str:
		"""Wait for the browser to start and return the CDP URL."""
		import aiohttp

		start_time = asyncio.get_event_loop().time()

		while asyncio.get_event_loop().time() - start_time < timeout:
			try:
				async with aiohttp.ClientSession() as session:
					async with session.get(f'http://localhost:{port}/json/version') as resp:
						if resp.status == 200:
							# Chrome is ready
							return f'http://localhost:{port}/'
						else:
							# Chrome is starting up and returning 502/500 errors
							await asyncio.sleep(0.1)
			except Exception:
				# Connection error - Chrome might not be ready yet
				await asyncio.sleep(0.1)

		raise TimeoutError(f'Browser did not start within {timeout} seconds')

	@staticmethod
	async def _cleanup_process(process: psutil.Process) -> None:
		"""Clean up browser process.

		Args:
			process: psutil.Process to terminate
		"""
		if not process:
			return

		try:
			# Try graceful shutdown first
			process.terminate()

			# Use async wait instead of blocking wait
			for _ in range(50):  # Wait up to 5 seconds (50 * 0.1)
				if not process.is_running():
					return
				await asyncio.sleep(0.1)

			# If still running after 5 seconds, force kill
			if process.is_running():
				process.kill()
				# Give it a moment to die
				await asyncio.sleep(0.1)

		except psutil.NoSuchProcess:
			# Process already gone
			pass
		except Exception:
			# Ignore any other errors during cleanup
			pass

	def _cleanup_temp_dir(self, temp_dir: Path | str) -> None:
		"""Clean up temporary directory.

		Args:
			temp_dir: Path to temporary directory to remove
		"""
		if not temp_dir:
			return

		try:
			temp_path = Path(temp_dir)
			# Only remove if it's actually a temp directory we created
			if 'browseruse-tmp-' in str(temp_path):
				shutil.rmtree(temp_path, ignore_errors=True)
		except Exception as e:
			self.logger.debug(f'Failed to cleanup temp dir {temp_dir}: {e}')

	@property
	def browser_pid(self) -> int | None:
		"""Get the browser process ID."""
		if self._subprocess:
			return self._subprocess.pid
		return None

	@staticmethod
	async def get_browser_pid_via_cdp(browser) -> int | None:
		"""Get the browser process ID via CDP SystemInfo.getProcessInfo.

		Args:
			browser: Playwright Browser instance

		Returns:
			Process ID or None if failed
		"""
		try:
			cdp_session = await browser.new_browser_cdp_session()
			result = await cdp_session.send('SystemInfo.getProcessInfo')
			process_info = result.get('processInfo', {})
			pid = process_info.get('id')
			await cdp_session.detach()
			return pid
		except Exception:
			# If we can't get PID via CDP, it's not critical
			return None
