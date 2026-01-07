import os
from unittest.mock import patch
from pathlib import Path
import pytest
from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog


@pytest.mark.asyncio
async def test_find_installed_browser_path_linux_new_structure():
	"""
	Regression test for Playwright 1.57.0+ path structure on Linux.
	Verifies that 'chrome-linux64' is correctly detected.
	"""
	with patch('platform.system', return_value='Linux'):
		with (
			patch('glob.glob') as mock_glob,
			patch('pathlib.Path.exists', autospec=True) as mock_exists,
			patch('pathlib.Path.is_file', autospec=True, return_value=True),
		):
			# Mock file existence check
			def exists_side_effect(self):
				path_str = str(self).replace('\\', '/')
				# Match the expected path from the new structure
				if 'chrome-linux64' in path_str and 'chrome' in path_str and 'chromium-' in path_str:
					return True
				return False

			mock_exists.side_effect = exists_side_effect

			# Mock glob to return the new path structure
			def glob_side_effect(pattern):
				# The code searches for: f'{playwright_path}/chromium-*/chrome-linux*/chrome'
				if 'chromium-*' in pattern and 'chrome-linux*' in pattern:
					return ['/home/user/.cache/ms-playwright/chromium-1001/chrome-linux64/chrome']
				return []

			mock_glob.side_effect = glob_side_effect

			path = LocalBrowserWatchdog._find_installed_browser_path()

			assert path is not None
			assert 'chrome-linux64' in path
			assert path == '/home/user/.cache/ms-playwright/chromium-1001/chrome-linux64/chrome'


@pytest.mark.asyncio
async def test_find_installed_browser_path_linux_old_structure():
	"""
	Regression test for legacy Playwright path structure on Linux.
	Verifies that 'chrome-linux' is still detected.
	"""
	with patch('platform.system', return_value='Linux'):
		with (
			patch('glob.glob') as mock_glob,
			patch('pathlib.Path.exists', autospec=True) as mock_exists,
			patch('pathlib.Path.is_file', autospec=True, return_value=True),
		):

			def exists_side_effect(self):
				path_str = str(self).replace('\\', '/')
				if 'chrome-linux' in path_str and 'chrome' in path_str and 'chromium-' in path_str:
					return True
				return False

			mock_exists.side_effect = exists_side_effect

			def glob_side_effect(pattern):
				if 'chromium-*' in pattern and 'chrome-linux*' in pattern:
					return ['/home/user/.cache/ms-playwright/chromium-1000/chrome-linux/chrome']
				return []

			mock_glob.side_effect = glob_side_effect

			path = LocalBrowserWatchdog._find_installed_browser_path()

			assert path is not None
			assert 'chrome-linux' in path
			assert 'chrome-linux64' not in path
			assert path == '/home/user/.cache/ms-playwright/chromium-1000/chrome-linux/chrome'
