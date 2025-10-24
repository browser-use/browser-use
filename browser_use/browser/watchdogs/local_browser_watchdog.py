"""Local browser watchdog for managing browser subprocess lifecycle."""

import asyncio
import glob
import os
import platform
import shutil
import socket
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import aiohttp
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
from browser_use.observability import observe_debug

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
	_temp_user_data_dir: Path | None = PrivateAttr(default=None)
	_original_user_data_dir: str | None = PrivateAttr(default=None)

	@observe_debug(ignore_input=True, ignore_output=True, name='browser_launch_event')
	async def on_BrowserLaunchEvent(self, event: BrowserLaunchEvent) -> BrowserLaunchResult:
		"""Launch a local browser process."""
		try:
			self.logger.debug('[LocalBrowserWatchdog] Received BrowserLaunchEvent, launching local browser...')
			process, cdp_url = await self._launch_browser()
			self._subprocess = process
			return BrowserLaunchResult(cdp_url=cdp_url)
		except Exception as e:
			self.logger.error(f'[LocalBrowserWatchdog] Exception in on_BrowserLaunchEvent: {e}', exc_info=True)
			raise

	async def on_BrowserKillEvent(self, event: BrowserKillEvent) -> None:
		"""Kill the local browser subprocess and clean up temporary profiles."""
		self.logger.debug('[LocalBrowserWatchdog] Killing local browser process')

		if self._subprocess:
			await self._cleanup_process(self._subprocess)
			self._subprocess = None

		# Clean up temporary cloned profile directory
		if self._temp_user_data_dir:
			self._cleanup_temp_dir(self._temp_user_data_dir)
			self._temp_user_data_dir = None

		# Restore original user_data_dir
		if self._original_user_data_dir is not None:
			self.browser_session.browser_profile.user_data_dir = self._original_user_data_dir
			self._original_user_data_dir = None

		self.logger.debug('[LocalBrowserWatchdog] Browser cleanup completed')

	async def on_BrowserStopEvent(self, event: BrowserStopEvent) -> None:
		"""Listen for BrowserStopEvent and dispatch BrowserKillEvent."""
		if self.browser_session.is_local and self._subprocess:
			self.logger.debug('[LocalBrowserWatchdog] BrowserStopEvent received, dispatching BrowserKillEvent')
			self.event_bus.dispatch(BrowserKillEvent())

	def _clone_profile(self, source_dir: Path, dest_dir: Path) -> None:
		"""Copy essential authentication data from a source profile to a destination.

		This copies cookies, login data, preferences, and other session data to allow
		the browser to start authenticated even when the source profile is locked.

		Args:
			source_dir: Source profile directory (e.g., ~/Library/Application Support/Google/Chrome/Default)
			dest_dir: Destination directory for the cloned profile
		"""
		self.logger.info(f'📋 Cloning profile data from {source_dir} to {dest_dir}')
		dest_dir.mkdir(parents=True, exist_ok=True)

		# Essential files for authentication and session persistence
		auth_files = ['Cookies', 'Login Data', 'Web Data', 'Preferences', 'Secure Preferences']

		# Copy files
		for filename in auth_files:
			source_file = source_dir / filename
			if source_file.exists():
				try:
					shutil.copy2(source_file, dest_dir / filename)
					self.logger.debug(f'✓ Copied {filename}')
				except Exception as e:
					self.logger.warning(f'Could not copy {filename}: {e}')

		# Copy essential directories for session storage
		dirs_to_copy = ['Local Storage', 'Session Storage']
		for dirname in dirs_to_copy:
			source_subdir = source_dir / dirname
			if source_subdir.is_dir():
				try:
					shutil.copytree(source_subdir, dest_dir / dirname, dirs_exist_ok=True)
					self.logger.debug(f'✓ Copied directory {dirname}')
				except Exception as e:
					self.logger.warning(f'Could not copy directory {dirname}: {e}')

	@observe_debug(ignore_input=True, ignore_output=True, name='launch_browser_process')
	async def _launch_browser(self) -> tuple[psutil.Process, str]:
		"""Launch browser process and return (process, cdp_url).

		If a user_data_dir is specified, this method will automatically create a temporary
		clone of the profile to avoid conflicts with running Chrome instances. This allows
		browser-use to work with authenticated sessions even when the main browser is open.

		Returns:
			Tuple of (psutil.Process, cdp_url)
		"""
		profile = self.browser_session.browser_profile
		self._original_user_data_dir = str(profile.user_data_dir) if profile.user_data_dir else None

		# If user_data_dir is specified, always clone to temporary directory to avoid conflicts
		if profile.user_data_dir:
			source_user_data_path = Path(profile.user_data_dir).expanduser().resolve()
			source_profile_subdir = source_user_data_path / profile.profile_directory

			if source_profile_subdir.exists():
				self.logger.info(f'🔄 Creating temporary authenticated session from {source_profile_subdir}')

				# Create temporary directory for this session
				self._temp_user_data_dir = Path(tempfile.mkdtemp(prefix='browseruse-cdp-'))
				dest_profile_subdir = self._temp_user_data_dir / profile.profile_directory

				# Clone authentication data
				self._clone_profile(source_profile_subdir, dest_profile_subdir)

				# **FIX:** Copy the 'Local State' file from the root user_data_dir for decryption keys.
				local_state_source = source_user_data_path / 'Local State'
				if local_state_source.exists():
					try:
						shutil.copy2(local_state_source, self._temp_user_data_dir / 'Local State')
						self.logger.debug('✓ Copied Local State file for decryption.')
					except Exception as e:
						self.logger.warning(f'Could not copy Local State file: {e}')

				# Use the temporary directory for this browser session
				profile.user_data_dir = str(self._temp_user_data_dir)
				self.logger.debug(f'📂 Using temporary profile: {self._temp_user_data_dir}')
			else:
				self.logger.warning(
					f'⚠️  Source profile {source_profile_subdir} does not exist. Proceeding with specified user_data_dir as-is.'
				)

		# Get launch args from profile
		launch_args = profile.get_args()

		# Add debugging port
		debug_port = self._find_free_port()
		launch_args.extend([f'--remote-debugging-port={debug_port}'])

		assert '--user-data-dir' in str(launch_args), (
			'User data dir must be set somewhere in launch args to a non-default path, '
			'otherwise Chrome will not let us attach via CDP'
		)

		# Get browser executable
		if profile.executable_path:
			browser_path = profile.executable_path
			self.logger.debug(f'📦 Using custom browser executable: {browser_path}')
		else:
			browser_path = self._find_installed_browser_path()
			if not browser_path:
				self.logger.error('⚠️  No local browser found, installing via Playwright...')
				browser_path = await self._install_browser_with_playwright()

		if not browser_path:
			raise RuntimeError('No local Chrome/Chromium install found, and failed to install with playwright')

		self.logger.debug(f'🚀 Launching browser: {browser_path}')

		# Launch browser subprocess
		subprocess = await asyncio.create_subprocess_exec(
			browser_path,
			*launch_args,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE,
		)

		self.logger.debug(f'🎭 Browser process started (PID: {subprocess.pid}) on CDP port: {debug_port}')

		# Convert to psutil.Process
		process = psutil.Process(subprocess.pid)

		# Wait for CDP to be ready
		cdp_url = await self._wait_for_cdp_url(debug_port)

		# Restore original user_data_dir in profile object for reference
		# (but keep temp dir for cleanup)
		if self._original_user_data_dir:
			profile.user_data_dir = self._original_user_data_dir

		return process, cdp_url

	@staticmethod
	def _find_installed_browser_path() -> str | None:
		"""Try to find browser executable from common fallback locations.

		Prioritizes:
		1. System Chrome Stable
		2. Playwright chromium
		3. Other system native browsers (Chromium -> Chrome Canary/Dev -> Brave)
		4. Playwright headless-shell fallback

		Returns:
			Path to browser executable or None if not found
		"""

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
			self.logger.debug(f'📦 Playwright install output: {stdout}')
			browser_path = self._find_installed_browser_path()
			if browser_path:
				return browser_path
			self.logger.error(f'❌ Playwright installation error:\n{stdout}\n{stderr}')
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

		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
			s.bind(('127.0.0.1', 0))
			s.listen(1)
			port = s.getsockname()[1]
		return port

	@staticmethod
	def _check_for_running_chrome_instances() -> list[tuple[int, list[str]]]:
		"""Check for running Chrome/Chromium processes.

		Returns:
			List of tuples (pid, cmdline) for each running Chrome process
		"""
		running_chrome: list[tuple[int, list[str]]] = []
		chrome_names = {'chrome', 'chromium', 'google chrome', 'chromium-browser'}
		# Electron apps to exclude (they use Chrome's engine but aren't Chrome)
		electron_apps = {
			'electron',
			'slack',
			'discord',
			'cursor',
			'vscode',
			'vs code',
			'visual studio code',
			'superhuman',
			'screen studio',
			'spotify',
			'drive',
			'adobe',
		}

		try:
			for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'exe']):
				try:
					name = proc.info.get('name', '').lower()
					cmdline = proc.info.get('cmdline', [])
					exe = (proc.info.get('exe') or '').lower()

					# Skip if it's an Electron app or other non-Chrome browser
					if any(app in name or app in exe for app in electron_apps):
						continue

					# Check if process name or exe path contains chrome/chromium
					if any(chrome_name in name or chrome_name in exe for chrome_name in chrome_names):
						# Exclude helper processes (they'll die with main process)
						# Also exclude crash handlers and other supporting processes
						if cmdline and '--type=' not in ' '.join(cmdline) and 'chrome_crashpad_handler' not in ' '.join(cmdline):
							running_chrome.append((proc.info['pid'], cmdline))
				except (psutil.NoSuchProcess, psutil.AccessDenied):
					continue
		except Exception:
			# If we can't check for processes, don't fail - just return empty list
			pass

		return running_chrome

	@staticmethod
	async def _wait_for_cdp_url(port: int, timeout: float = 30) -> str:
		"""Wait for the browser to start and return the CDP URL."""

		start_time = asyncio.get_event_loop().time()

		while asyncio.get_event_loop().time() - start_time < timeout:
			try:
				async with aiohttp.ClientSession() as session:
					async with session.get(
						f'http://127.0.0.1:{port}/json/version', timeout=aiohttp.ClientTimeout(total=2)
					) as resp:
						if resp.status == 200:
							# Chrome is ready
							return f'http://127.0.0.1:{port}/'
						else:
							# Chrome is starting up and returning 502/500 errors
							await asyncio.sleep(0.1)
			except Exception:
				# Connection error - Chrome might not be ready yet
				await asyncio.sleep(0.1)

		# Check if Chrome is already running with debugging enabled before raising
		running_chrome = LocalBrowserWatchdog._check_for_running_chrome_instances()
		if running_chrome:
			raise RuntimeError(
				f'Browser failed to start on port {port} within {timeout} seconds.\n\n'
				f'⚠️  IMPORTANT: Detected {len(running_chrome)} Chrome/Chromium instance(s) already running:\n'
				+ '\n'.join(f'  • PID {pid}: {" ".join(cmd[:3])}...' for pid, cmd in running_chrome)
				+ '\n\n'
				'browser-use requires exclusive control over Chrome to enable CDP debugging.\n'
				'Please close ALL Chrome/Chromium windows and try again:\n'
				'  • macOS: Cmd+Q to quit Chrome completely\n'
				'  • Linux/Windows: File → Exit or killall chrome\n\n'
				'If Chrome is stuck, force quit with:\n'
				'  • macOS: killall "Google Chrome" "Chromium"\n'
				'  • Linux: killall chrome chromium-browser\n'
				'  • Windows: taskkill /F /IM chrome.exe'
			)

		raise TimeoutError(f'Browser did not start within {timeout} seconds')

	async def _cleanup_process(self, process: psutil.Process) -> None:
		"""Gracefully terminate a process and its entire process tree."""
		if not process or not process.is_running():
			return
		try:
			# Terminate children first
			children = process.children(recursive=True)
			for child in children:
				try:
					child.terminate()
				except psutil.NoSuchProcess:
					pass

			# Wait for children to terminate
			gone, alive = psutil.wait_procs(children, timeout=3)
			# Force kill any remaining children
			for p in alive:
				p.kill()

			# Terminate the main process
			process.terminate()
			await asyncio.sleep(0.5)
			if process.is_running():
				process.kill()
		except psutil.NoSuchProcess:
			# Process already gone
			pass
		except Exception as e:
			self.logger.warning(f'Error during process cleanup: {e}')

	def _cleanup_temp_dir(self, temp_dir: Path | str) -> None:
		"""Clean up the temporary profile directory."""
		if not temp_dir:
			return
		try:
			self.logger.info(f'🧹 Cleaning up temporary profile directory: {temp_dir}')
			shutil.rmtree(temp_dir, ignore_errors=True)
		except Exception as e:
			self.logger.warning(f'Failed to cleanup temp dir {temp_dir}: {e}')

	@property
	def browser_pid(self) -> int | None:
		"""Get the browser process ID."""
		return self._subprocess.pid if self._subprocess else None

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
