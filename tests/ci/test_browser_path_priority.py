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

# macOS paths
MAC_CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
MAC_PW_CHROMIUM = '/Users/ci/Library/Caches/ms-playwright/chromium-1148/chrome-mac/Chromium.app/Contents/MacOS/Chromium'

# Linux paths
LINUX_CHROME = '/usr/bin/google-chrome-stable'
LINUX_PW_CHROMIUM = '/home/ci/.cache/ms-playwright/chromium-1148/chrome-linux64/chrome'


def _path_checker(*valid_paths: str):
	"""Return a Path method mock that returns True only for listed paths."""

	def check(self):
		return str(self) in valid_paths

	return check


def _strict_glob_mock(expected_substr: str, result: list[str]):
	"""Return a glob.glob mock that only matches patterns containing expected_substr."""

	def mock(pattern):
		if expected_substr in pattern:
			return result
		return []

	return mock


@pytest.fixture(params=['Darwin', 'Linux'], ids=['macOS', 'Linux'])
def platform_paths(request):
	"""Provide platform-specific browser paths."""
	if request.param == 'Darwin':
		return {
			'system': request.param,
			'chrome': MAC_CHROME,
			'pw_chromium': MAC_PW_CHROMIUM,
			'pw_glob_substr': 'ms-playwright/chromium-',
		}
	return {
		'system': request.param,
		'chrome': LINUX_CHROME,
		'pw_chromium': LINUX_PW_CHROMIUM,
		'pw_glob_substr': 'ms-playwright/chromium-',
	}


class TestBrowserPathPriority:
	"""_find_installed_browser_path priority ordering."""

	def test_default_prefers_playwright_chromium(self, platform_paths):
		"""Default channel returns Playwright Chromium when both it and Chrome exist."""
		pp = platform_paths
		checker = _path_checker(pp['chrome'], pp['pw_chromium'])
		glob_fn = _strict_glob_mock(pp['pw_glob_substr'], [pp['pw_chromium']])
		with (
			patch('platform.system', return_value=pp['system']),
			patch.object(Path, 'exists', checker),
			patch.object(Path, 'is_file', checker),
			patch('glob.glob', glob_fn),
		):
			result = LocalBrowserWatchdog._find_installed_browser_path(channel=None)
		assert result == pp['pw_chromium']

	def test_chrome_channel_prefers_system_chrome(self, platform_paths):
		"""Explicit CHROME channel returns system Chrome first."""
		pp = platform_paths
		checker = _path_checker(pp['chrome'], pp['pw_chromium'])
		glob_fn = _strict_glob_mock(pp['pw_glob_substr'], [pp['pw_chromium']])
		with (
			patch('platform.system', return_value=pp['system']),
			patch.object(Path, 'exists', checker),
			patch.object(Path, 'is_file', checker),
			patch('glob.glob', glob_fn),
		):
			result = LocalBrowserWatchdog._find_installed_browser_path(channel=BrowserChannel.CHROME)
		assert result == pp['chrome']

	def test_explicit_chromium_same_as_default(self, platform_paths):
		"""Explicit CHROMIUM channel behaves identically to default."""
		pp = platform_paths
		checker = _path_checker(pp['chrome'], pp['pw_chromium'])
		glob_fn = _strict_glob_mock(pp['pw_glob_substr'], [pp['pw_chromium']])
		with (
			patch('platform.system', return_value=pp['system']),
			patch.object(Path, 'exists', checker),
			patch.object(Path, 'is_file', checker),
			patch('glob.glob', glob_fn),
		):
			result = LocalBrowserWatchdog._find_installed_browser_path(channel=BrowserChannel.CHROMIUM)
		assert result == pp['pw_chromium']

	def test_fallback_when_chromium_missing(self, platform_paths):
		"""When Playwright Chromium is not installed, falls back to system Chrome."""
		pp = platform_paths
		checker = _path_checker(pp['chrome'])
		with (
			patch('platform.system', return_value=pp['system']),
			patch.object(Path, 'exists', checker),
			patch.object(Path, 'is_file', checker),
			patch('glob.glob', return_value=[]),
		):
			result = LocalBrowserWatchdog._find_installed_browser_path(channel=None)
		assert result == pp['chrome']

	def test_returns_none_when_nothing_installed(self, platform_paths):
		"""Returns None when no browser is found."""
		with (
			patch('platform.system', return_value=platform_paths['system']),
			patch.object(Path, 'exists', lambda self: False),
			patch.object(Path, 'is_file', lambda self: False),
			patch('glob.glob', return_value=[]),
		):
			result = LocalBrowserWatchdog._find_installed_browser_path(channel=None)
		assert result is None

	def test_glob_selects_highest_version(self):
		"""When multiple Playwright versions exist, the highest one is selected by the function."""
		v1 = '/Users/ci/Library/Caches/ms-playwright/chromium-1100/chrome-mac/Chromium.app/Contents/MacOS/Chromium'
		v2 = '/Users/ci/Library/Caches/ms-playwright/chromium-1200/chrome-mac/Chromium.app/Contents/MacOS/Chromium'
		checker = _path_checker(v1, v2)
		glob_fn = _strict_glob_mock('ms-playwright/chromium-', [v1, v2])
		with (
			patch('platform.system', return_value='Darwin'),
			patch.object(Path, 'exists', checker),
			patch.object(Path, 'is_file', checker),
			patch('glob.glob', glob_fn),
		):
			result = LocalBrowserWatchdog._find_installed_browser_path(channel=None)
		# Function sorts glob results and takes the last (highest version)
		assert result == v2
