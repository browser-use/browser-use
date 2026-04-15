"""Regression tests for browser path discovery priority (#4664).

PR #4664 changed the default to prefer Playwright's bundled Chromium over
system Chrome. These tests prevent accidental regression of the priority
logic in LocalBrowserWatchdog._find_installed_browser_path.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from browser_use.browser.profile import BrowserChannel
from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog

CHROME_PATH = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
PW_CHROMIUM_PATH = '/Users/ci/Library/Caches/ms-playwright/chromium-1148/chrome-mac/Chromium.app/Contents/MacOS/Chromium'
EDGE_PATH = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'


def _path_checker(*valid_paths: str):
	"""Return a Path method mock that returns True only for listed paths."""

	def check(self):
		return str(self) in valid_paths

	return check


def _glob_mock(*rules: tuple[str, list[str]]):
	"""Return a glob.glob mock: if substring matches pattern, return results."""

	def mock(pattern):
		for substr, result in rules:
			if substr in pattern:
				return result
		return []

	return mock


@pytest.fixture()
def _darwin():
	with patch('platform.system', return_value='Darwin'):
		yield


@pytest.mark.usefixtures('_darwin')
class TestBrowserPathPriority:
	"""_find_installed_browser_path priority ordering."""

	def test_default_prefers_playwright_chromium(self):
		"""Default channel returns Playwright Chromium when both it and Chrome exist."""
		checker = _path_checker(CHROME_PATH, PW_CHROMIUM_PATH)
		with (
			patch.object(Path, 'exists', checker),
			patch.object(Path, 'is_file', checker),
			patch('glob.glob', _glob_mock(('chromium-', [PW_CHROMIUM_PATH]))),
		):
			result = LocalBrowserWatchdog._find_installed_browser_path(channel=None)
		assert result == PW_CHROMIUM_PATH

	def test_chrome_channel_prefers_system_chrome(self):
		"""Explicit CHROME channel returns system Chrome first."""
		checker = _path_checker(CHROME_PATH, PW_CHROMIUM_PATH)
		with (
			patch.object(Path, 'exists', checker),
			patch.object(Path, 'is_file', checker),
			patch('glob.glob', _glob_mock(('chromium-', [PW_CHROMIUM_PATH]))),
		):
			result = LocalBrowserWatchdog._find_installed_browser_path(channel=BrowserChannel.CHROME)
		assert result == CHROME_PATH

	def test_explicit_chromium_same_as_default(self):
		"""Explicit CHROMIUM channel behaves identically to default."""
		checker = _path_checker(CHROME_PATH, PW_CHROMIUM_PATH)
		with (
			patch.object(Path, 'exists', checker),
			patch.object(Path, 'is_file', checker),
			patch('glob.glob', _glob_mock(('chromium-', [PW_CHROMIUM_PATH]))),
		):
			result = LocalBrowserWatchdog._find_installed_browser_path(channel=BrowserChannel.CHROMIUM)
		assert result == PW_CHROMIUM_PATH

	def test_fallback_to_chrome_when_chromium_missing(self):
		"""When Playwright Chromium is not installed, falls back to system Chrome."""
		checker = _path_checker(CHROME_PATH)
		with (
			patch.object(Path, 'exists', checker),
			patch.object(Path, 'is_file', checker),
			patch('glob.glob', return_value=[]),
		):
			result = LocalBrowserWatchdog._find_installed_browser_path(channel=None)
		assert result == CHROME_PATH

	def test_returns_none_when_nothing_installed(self):
		"""Returns None when no browser is found."""
		with (
			patch.object(Path, 'exists', lambda self: False),
			patch.object(Path, 'is_file', lambda self: False),
			patch('glob.glob', return_value=[]),
		):
			result = LocalBrowserWatchdog._find_installed_browser_path(channel=None)
		assert result is None
