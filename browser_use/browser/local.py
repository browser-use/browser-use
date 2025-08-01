"""Local browser helpers for process management."""

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import psutil
from playwright.async_api import async_playwright

from browser_use.browser.profile import BrowserProfile
from browser_use.utils import logger

if TYPE_CHECKING:
	pass


class LocalBrowserHelpers:
	"""Static helper methods for local browser operations."""

	@staticmethod
	async def launch_browser(profile: BrowserProfile, max_retries: int = 3) -> tuple[psutil.Process, str]:
		"""Launch browser process and return (process, cdp_url).

		Handles launch errors by falling back to temporary directories if needed.

		Args:
			profile: Browser configuration profile
			max_retries: Maximum number of launch attempts

		Returns:
			Tuple of (psutil.Process, cdp_url)
		"""
		# Keep track of original user_data_dir to restore if needed
		original_user_data_dir = profile.user_data_dir
		tmp_dirs_to_cleanup = []

		for attempt in range(max_retries):
			try:
				# Get launch args from profile
				launch_args = profile.args_for_browser_launch()

				# Add debugging port
				debug_port = LocalBrowserHelpers.find_free_port()
				launch_args.extend(
					[
						f'--remote-debugging-port={debug_port}',
					]
				)

				# Get browser executable from playwright
				playwright = await async_playwright().start()
				try:
					# Use custom executable if provided, otherwise use playwright's
					if profile.executable_path:
						browser_path = profile.executable_path
					else:
						browser_path = playwright.chromium.executable_path

					# Launch browser subprocess directly
					subprocess = await asyncio.create_subprocess_exec(
						browser_path,
						*launch_args,
						stdout=asyncio.subprocess.PIPE,
						stderr=asyncio.subprocess.PIPE,
					)

					# Convert to psutil.Process
					process = psutil.Process(subprocess.pid)

					# Wait for CDP to be ready and get the URL
					cdp_url = await LocalBrowserHelpers.wait_for_cdp_url(debug_port)

					# Success! Clean up any temp dirs we created but didn't use
					for tmp_dir in tmp_dirs_to_cleanup:
						try:
							shutil.rmtree(tmp_dir, ignore_errors=True)
						except Exception:
							pass

					return process, cdp_url

				finally:
					# Clean up playwright instance
					await playwright.stop()

			except Exception as e:
				error_str = str(e).lower()

				# Check if this is a user_data_dir related error
				if any(err in error_str for err in ['singletonlock', 'user data directory', 'cannot create', 'already in use']):
					logger.warning(f'Browser launch failed (attempt {attempt + 1}/{max_retries}): {e}')

					if attempt < max_retries - 1:
						# Create a temporary directory for next attempt
						tmp_dir = Path(tempfile.mkdtemp(prefix='browseruse-tmp-'))
						tmp_dirs_to_cleanup.append(tmp_dir)

						# Update profile to use temp directory
						profile.user_data_dir = str(tmp_dir)
						logger.info(f'Retrying with temporary user_data_dir: {tmp_dir}')

						# Small delay before retry
						await asyncio.sleep(0.5)
						continue

				# Not a recoverable error or last attempt failed
				# Restore original user_data_dir before raising
				profile.user_data_dir = original_user_data_dir

				# Clean up any temp dirs we created
				for tmp_dir in tmp_dirs_to_cleanup:
					try:
						shutil.rmtree(tmp_dir, ignore_errors=True)
					except Exception:
						pass

				raise

		# Should not reach here, but just in case
		profile.user_data_dir = original_user_data_dir
		raise RuntimeError(f'Failed to launch browser after {max_retries} attempts')

	@staticmethod
	def find_free_port() -> int:
		"""Find a free port for the debugging interface."""
		import socket

		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
			s.bind(('127.0.0.1', 0))
			s.listen(1)
			port = s.getsockname()[1]
		return port

	@staticmethod
	async def wait_for_cdp_url(port: int, timeout: float = 30) -> str:
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

	@staticmethod
	async def cleanup_process(process: psutil.Process) -> None:
		"""Clean up browser process.

		Args:
			process: psutil.Process to terminate
		"""
		if not process:
			return

		try:
			# Try graceful shutdown first
			process.terminate()
			# Wait up to 5 seconds for process to exit
			process.wait(timeout=5)
		except psutil.TimeoutExpired:
			# Force kill if needed
			try:
				process.kill()
			except psutil.NoSuchProcess:
				pass
		except psutil.NoSuchProcess:
			# Process already gone
			pass

	@staticmethod
	def cleanup_temp_dir(temp_dir: Path | str) -> None:
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
			logger.debug(f'Failed to cleanup temp dir {temp_dir}: {e}')
