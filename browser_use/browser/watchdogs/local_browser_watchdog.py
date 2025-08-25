"""Local browser watchdog for managing browser subprocess lifecycle."""

import asyncio
import os
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
	BrowserLaunchResult,
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

	async def on_BrowserLaunchEvent(self, event: BrowserLaunchEvent) -> BrowserLaunchResult:
		"""Launch a local browser process."""

		try:
			self.logger.debug('[LocalBrowserWatchdog] Received BrowserLaunchEvent, launching local browser...')

			# self.logger.debug('[LocalBrowserWatchdog] Calling _launch_browser...')
			process, cdp_url = await self._launch_browser()
			self._subprocess = process
			# self.logger.debug(f'[LocalBrowserWatchdog] _launch_browser returned: process={process}, cdp_url={cdp_url}')

			return BrowserLaunchResult(cdp_url=cdp_url)
		except Exception as e:
			self.logger.error(f'[LocalBrowserWatchdog] Exception in on_BrowserLaunchEvent: {e}', exc_info=True)
			raise

	async def on_BrowserKillEvent(self, event: BrowserKillEvent) -> None:
		"""Kill the local browser subprocess."""
		self.logger.debug('[LocalBrowserWatchdog] Killing local browser process')

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

		self.logger.debug('[LocalBrowserWatchdog] Browser cleanup completed')

	async def on_BrowserStopEvent(self, event: BrowserStopEvent) -> None:
		"""Listen for BrowserStopEvent and dispatch BrowserKillEvent without awaiting it."""
		if self.browser_session.is_local and self._subprocess:
			self.logger.debug('[LocalBrowserWatchdog] BrowserStopEvent received, dispatching BrowserKillEvent')
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
				assert '--user-data-dir' in str(launch_args), (
					'User data dir must be set somewhere in launch args to a non-default path, otherwise Chrome will not let us attach via CDP'
				)

				# Get browser executable
				# Priority: custom executable > fallback paths > playwright subprocess
				if profile.executable_path:
					browser_path = profile.executable_path
					self.logger.debug(f'[LocalBrowserWatchdog] 📦 Using custom local browser executable_path= {browser_path}')
				else:
					# self.logger.debug('[LocalBrowserWatchdog] 🔍 Looking for local browser binary path...')
					# Try fallback paths first (system browsers preferred)
					browser_path = self._find_installed_browser_path()
					if not browser_path:
						self.logger.error(
							'[LocalBrowserWatchdog] ⚠️ No local browser binary found, installing browser using playwright subprocess...'
						)
						browser_path = await self._install_browser_with_playwright()

				self.logger.debug(f'[LocalBrowserWatchdog] 📦 Found local browser installed at executable_path= {browser_path}')
				if not browser_path:
					raise RuntimeError('No local Chrome/Chromium install found, and failed to install with playwright')

				# Launch browser subprocess directly
				self.logger.debug(f'[LocalBrowserWatchdog] 🚀 Launching browser subprocess with {len(launch_args)} args...')
				subprocess = await asyncio.create_subprocess_exec(
					browser_path,
					*launch_args,
					stdout=asyncio.subprocess.PIPE,
					stderr=asyncio.subprocess.PIPE,
				)
				self.logger.debug(
					f'[LocalBrowserWatchdog] 🎭 Browser running with browser_pid= {subprocess.pid} 🔗 listening on CDP port :{debug_port}'
				)

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
						self.logger.debug(f'Retrying with temporary user_data_dir: {tmp_dir}')

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
	def _find_installed_browser_path() -> str | None:
		"""Try to find browser executable from common fallback locations.

		Prioritizes:
		1. System Chrome Stable
		1. Playwright chromium
		2. Other system native browsers (Chromium -> Chrome Canary/Dev -> Brave)
		3. Playwright headless-shell fallback

		Returns:
			Path to browser executable or None if not found
		"""
		import glob
		import platform
		from pathlib import Path

		system = platform.system()
		patterns = []

		# Get playwright browsers path from environment variable if set
		playwright_path = os.environ.get('PLAYWRIGHT_BROWSERS_PATH')

		if system == 'Darwin':  # macOS
			if not playwright_path:
				playwright_path = '~/Library/Caches/ms-playwright'
			patterns = [
				'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
				f'{playwright_path}/chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium',
				'/Applications/Chromium.app/Contents/MacOS/Chromium',
				'/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
				'/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
				f'{playwright_path}/chromium_headless_shell-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium',
			]
		elif system == 'Linux':
			if not playwright_path:
				playwright_path = '~/.cache/ms-playwright'
			patterns = [
				'/usr/bin/google-chrome-stable',
				'/usr/bin/google-chrome',
				'/usr/local/bin/google-chrome',
				f'{playwright_path}/chromium-*/chrome-linux/chrome',
				'/usr/bin/chromium',
				'/usr/bin/chromium-browser',
				'/usr/local/bin/chromium',
				'/snap/bin/chromium',
				'/usr/bin/google-chrome-beta',
				'/usr/bin/google-chrome-dev',
				'/usr/bin/brave-browser',
				f'{playwright_path}/chromium_headless_shell-*/chrome-linux/chrome',
			]
		elif system == 'Windows':
			if not playwright_path:
				playwright_path = r'%LOCALAPPDATA%\ms-playwright'
			patterns = [
				r'C:\Program Files\Google\Chrome\Application\chrome.exe',
				r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
				r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe',
				r'%PROGRAMFILES%\Google\Chrome\Application\chrome.exe',
				r'%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe',
				f'{playwright_path}\\chromium-*\\chrome-win\\chrome.exe',
				r'C:\Program Files\Chromium\Application\chrome.exe',
				r'C:\Program Files (x86)\Chromium\Application\chrome.exe',
				r'%LOCALAPPDATA%\Chromium\Application\chrome.exe',
				r'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe',
				r'C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe',
				r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
				r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
				r'%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe',
				f'{playwright_path}\\chromium_headless_shell-*\\chrome-win\\chrome.exe',
			]

		for pattern in patterns:
			# Expand user home directory
			expanded_pattern = Path(pattern).expanduser()

			# Handle Windows environment variables
			if system == 'Windows':
				pattern_str = str(expanded_pattern)
				for env_var in ['%LOCALAPPDATA%', '%PROGRAMFILES%', '%PROGRAMFILES(X86)%']:
					if env_var in pattern_str:
						env_key = env_var.strip('%').replace('(X86)', ' (x86)')
						env_value = os.environ.get(env_key, '')
						if env_value:
							pattern_str = pattern_str.replace(env_var, env_value)
				expanded_pattern = Path(pattern_str)

			# Convert to string for glob
			pattern_str = str(expanded_pattern)

			# Check if pattern contains wildcards
			if '*' in pattern_str:
				# Use glob to expand the pattern
				matches = glob.glob(pattern_str)
				if matches:
					# Sort matches and take the last one (alphanumerically highest version)
					matches.sort()
					browser_path = matches[-1]
					if Path(browser_path).exists() and Path(browser_path).is_file():
						return browser_path
			else:
				# Direct path check
				if expanded_pattern.exists() and expanded_pattern.is_file():
					return str(expanded_pattern)

		return None

	async def _install_browser_with_playwright(self) -> str:
		"""Get browser executable path from playwright in a subprocess to avoid thread issues."""

		# Run in subprocess with timeout
		process = await asyncio.create_subprocess_exec(
			'uvx',
			'playwright',
			'install',
			'chrome',
			'--with-deps',
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE,
		)

		try:
			stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60.0)
			self.logger.debug(f'[LocalBrowserWatchdog] 📦 Playwright install output: {stdout}')
			browser_path = self._find_installed_browser_path()
			if browser_path:
				return browser_path
			self.logger.error(f'[LocalBrowserWatchdog] ❌ Playwright local browser installation error: \n{stdout}\n{stderr}')
			raise RuntimeError('No local browser path found after: uvx playwright install chrome --with-deps')
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
