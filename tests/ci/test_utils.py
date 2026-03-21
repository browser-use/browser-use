"""Tests for skill_cli/utils.py"""

from pathlib import Path
from unittest.mock import patch

import pytest

from browser_use.skill_cli.utils import get_chrome_profile_path


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

	def test_get_chrome_profile_path_linux_chromium_exists(self):
		"""Test Linux: returns ~/.config/chromium when it exists as a directory."""
		with patch('platform.system', return_value='Linux'):
			original_is_dir = Path.is_dir

			def mock_is_dir(self_path):
				if str(self_path).endswith('chromium'):
					return True
				return original_is_dir(self_path)

			with patch.object(Path, 'is_dir', mock_is_dir):
				result = get_chrome_profile_path(None)
			# Use Path to normalize for cross-platform assertion
			assert Path(result).name == 'chromium'

	def test_get_chrome_profile_path_linux_chromium_missing(self):
		"""Test Linux: falls back to ~/.config/google-chrome when chromium doesn't exist."""
		with patch('platform.system', return_value='Linux'):

			def mock_is_dir_false(self_path):
				return False

			with patch.object(Path, 'is_dir', mock_is_dir_false):
				result = get_chrome_profile_path(None)
			# Use Path to normalize for cross-platform assertion
			assert Path(result).name == 'google-chrome'
