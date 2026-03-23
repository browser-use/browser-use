"""Tests for skill_cli/utils.py."""

import pathlib
from pathlib import Path
from unittest.mock import patch

import pytest

from browser_use.skill_cli.utils import get_chrome_profile_path


# Cache the real is_dir before any mock can shadow it
_real_is_dir = pathlib.Path.is_dir


def _make_linux_is_dir_mock(chromium_dir=True, google_chrome_dir=True):
	"""Create an is_dir mock for Linux Chrome profile paths on any platform."""

	def mock_is_dir(self_path):
		name = self_path.name  # Use .name to be OS-agnostic
		if name == 'chromium':
			return chromium_dir
		if name == 'google-chrome':
			return google_chrome_dir
		# For other paths (e.g., sock_file), fall back to the real is_dir
		# by calling pathlib.Path.is_dir directly to avoid mock recursion
		return _real_is_dir(Path(self_path))

	return mock_is_dir


class TestGetChromeProfilePath:
	"""Tests for get_chrome_profile_path."""

	def test_get_chrome_profile_path_with_profile_name(self):
		"""Test that a profile name is returned as-is."""
		result = get_chrome_profile_path('my-profile')
		assert result == 'my-profile'

	def test_get_chrome_profile_path_null_macos(self):
		"""Test that macOS returns the default Chrome path when profile is None."""
		with patch('platform.system', return_value='Darwin'):
			result = get_chrome_profile_path(None)
		expected = str(Path.home() / 'Library' / 'Application Support' / 'Google' / 'Chrome')
		assert result == expected

	def test_get_chrome_profile_path_null_windows(self):
		"""Test that Windows returns the default Chrome path when profile is None."""
		with patch('platform.system', return_value='Windows'):
			with patch('os.path.expandvars', side_effect=lambda x: x):
				result = get_chrome_profile_path(None)
		assert 'Chrome' in result or 'User Data' in result

	def test_get_chrome_profile_path_linux_chromium_detected(self):
		"""Test Linux: returns ~/.config/chromium when chromium executable is detected."""
		with patch('platform.system', return_value='Linux'):
			with patch('browser_use.skill_cli.utils.find_chrome_executable', return_value='/usr/bin/chromium'):
				with patch.object(Path, 'is_dir', _make_linux_is_dir_mock(chromium_dir=True, google_chrome_dir=False)):
					result = get_chrome_profile_path(None)
				assert Path(result).name == 'chromium'

	def test_get_chrome_profile_path_linux_google_chrome_detected(self):
		"""Test Linux: returns ~/.config/google-chrome when google-chrome is detected."""
		with patch('platform.system', return_value='Linux'):
			with patch('browser_use.skill_cli.utils.find_chrome_executable', return_value='/usr/bin/google-chrome'):
				with patch.object(Path, 'is_dir', _make_linux_is_dir_mock(chromium_dir=False, google_chrome_dir=True)):
					result = get_chrome_profile_path(None)
				assert Path(result).name == 'google-chrome'

	def test_get_chrome_profile_path_linux_google_chrome_detected_no_dirs(self):
		"""Test Linux: returns google-chrome path when google-chrome detected but neither dir exists."""
		with patch('platform.system', return_value='Linux'):
			with patch('browser_use.skill_cli.utils.find_chrome_executable', return_value='/usr/bin/google-chrome'):
				# Neither chromium nor google-chrome directory exists
				with patch.object(Path, 'is_dir', _make_linux_is_dir_mock(chromium_dir=False, google_chrome_dir=False)):
					result = get_chrome_profile_path(None)
				# google-chrome detected → returns google-chrome path
				assert Path(result).name == 'google-chrome'

	def test_get_chrome_profile_path_linux_no_executable_fallback(self):
		"""Test Linux: falls back to chromium when no executable is detected."""
		with patch('platform.system', return_value='Linux'):
			with patch('browser_use.skill_cli.utils.find_chrome_executable', return_value=None):
				with patch.object(Path, 'is_dir', _make_linux_is_dir_mock(chromium_dir=True, google_chrome_dir=False)):
					result = get_chrome_profile_path(None)
				assert Path(result).name == 'chromium'

	def test_get_chrome_profile_path_linux_no_browser_found(self):
		"""Test Linux: returns google-chrome path when neither browser directory exists."""
		with patch('platform.system', return_value='Linux'):
			with patch('browser_use.skill_cli.utils.find_chrome_executable', return_value=None):
				with patch.object(Path, 'is_dir', _make_linux_is_dir_mock(chromium_dir=False, google_chrome_dir=False)):
					result = get_chrome_profile_path(None)
				assert Path(result).name == 'google-chrome'
