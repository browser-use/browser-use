"""Tests for browser_use/skill_cli/utils.py"""

import platform
from pathlib import Path
from unittest.mock import patch

import pytest

from browser_use.skill_cli.utils import (
    _is_chromium_browser,
    get_chrome_profile_path,
    get_chrome_user_data_dirs,
)


def _normalize_path(p: Path) -> str:
    """Normalize a Path to forward-slash string for cross-platform test comparisons."""
    return p.as_posix()


class TestGetChromeUserDataDirs:
    """Test get_chrome_user_data_dirs() correctly filters by is_dir()."""

    def test_linux_returns_only_existing_dirs(self):
        """Only directories that actually exist (is_dir returns True) are returned.

        The key issue this tests resolves: a naive mock that calls self.exists()
        inside the fake is_dir function causes infinite recursion because
        exists() internally uses is_dir(). The correct approach stores the real
        Path.is_dir method and calls it via a side_effect that bypasses the mock.
        """
        def fake_is_dir(self):
            # Use as_posix() for cross-platform path normalization
            path_str = self.as_posix()
            existing = {
                '/home/user/.config/google-chrome',
                '/home/user/.config/chromium',
            }
            return path_str in existing

        mock_home = Path('/home/user')
        candidates_checked = []

        def tracking_is_dir(self):
            candidates_checked.append(str(self))
            return fake_is_dir(self)

        with patch.object(Path, 'home', return_value=mock_home):
            with patch.object(Path, 'is_dir', tracking_is_dir):
                with patch('browser_use.skill_cli.utils.platform.system', return_value='Linux'):
                    result = get_chrome_user_data_dirs()

        # Verify correct candidates were checked
        normalized_checked = [_normalize_path(Path(c)) for c in candidates_checked]
        assert '/home/user/.config/google-chrome' in normalized_checked
        assert '/home/user/.config/chromium' in normalized_checked
        assert '/home/user/.config/BraveSoftware/Brave-Browser' in normalized_checked

        # Only existing dirs should be in result
        result_strs = [_normalize_path(p) for p in result]
        assert '/home/user/.config/google-chrome' in result_strs
        assert '/home/user/.config/chromium' in result_strs
        assert '/home/user/.config/BraveSoftware/Brave-Browser' not in result_strs

    def test_macos_returns_only_existing_dirs(self):
        """On macOS only existing directories under ~/Library/Application Support are returned."""
        def fake_is_dir(self):
            path_str = self.as_posix()
            existing = {'/home/user/Library/Application Support/Google/Chrome'}
            return path_str in existing

        mock_home = Path('/home/user')

        with patch.object(Path, 'home', return_value=mock_home):
            with patch.object(Path, 'is_dir', fake_is_dir):
                with patch('browser_use.skill_cli.utils.platform.system', return_value='Darwin'):
                    result = get_chrome_user_data_dirs()

        result_strs = [_normalize_path(p) for p in result]
        assert '/home/user/Library/Application Support/Google/Chrome' in result_strs
        assert '/home/user/Library/Application Support/Chromium' not in result_strs

    def test_windows_returns_only_existing_dirs(self):
        """On Windows only existing directories under %LOCALAPPDATA% are returned."""
        def fake_is_dir(self):
            path_str = _normalize_path(self)
            existing = {'C:/Users/user/AppData/Local/Google/Chrome/User Data'}
            return path_str in existing

        mock_home = Path('C:/Users/user')

        with patch.object(Path, 'home', return_value=mock_home):
            with patch.object(Path, 'is_dir', fake_is_dir):
                with patch('browser_use.skill_cli.utils.platform.system', return_value='Windows'):
                    with patch('browser_use.skill_cli.utils.os.environ.get', side_effect=lambda k, d=None: {
                        'LOCALAPPDATA': 'C:\\Users\\user\\AppData\\Local',
                    }.get(k, d)):
                        result = get_chrome_user_data_dirs()

        result_strs = [_normalize_path(p) for p in result]
        assert 'C:/Users/user/AppData/Local/Google/Chrome/User Data' in result_strs
        assert 'C:/Users/user/AppData/Local/Chromium/User Data' not in result_strs


class TestIsChromiumBrowser:
    """Test _is_chromium_browser() correctly identifies Chromium-based browsers."""

    def test_none_returns_false(self):
        assert _is_chromium_browser(None) is False

    def test_chromium_returns_true(self):
        assert _is_chromium_browser('/usr/bin/chromium') is True
        assert _is_chromium_browser('/usr/bin/chromium-browser') is True

    def test_google_chrome_returns_false(self):
        assert _is_chromium_browser('/usr/bin/google-chrome') is False
        assert _is_chromium_browser('/usr/bin/google-chrome-stable') is False

    def test_brave_returns_true(self):
        assert _is_chromium_browser('/usr/bin/brave-browser') is True

    def test_edge_returns_true(self):
        assert _is_chromium_browser('/usr/bin/microsoft-edge') is True

    def test_windows_chrome_returns_false(self):
        assert _is_chromium_browser('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe') is False

    def test_windows_chromium_returns_true(self):
        assert _is_chromium_browser('C:\\Program Files\\Chromium\\Application\\chrome.exe') is True


class TestGetChromeProfilePath:
    """Test get_chrome_profile_path() with the executable_path parameter on Linux."""

    def test_linux_chromium_profile_path(self):
        """On Linux with Chromium executable, return the Chromium profile path."""
        with patch('browser_use.skill_cli.utils.platform.system', return_value='Linux'):
            result = get_chrome_profile_path(None, executable_path='/usr/bin/chromium')
        expected = str(Path.home() / '.config' / 'chromium')
        assert result == expected

    def test_linux_chromium_browser_profile_path(self):
        """On Linux with chromium-browser executable, return the Chromium profile path."""
        with patch('browser_use.skill_cli.utils.platform.system', return_value='Linux'):
            result = get_chrome_profile_path(None, executable_path='/usr/bin/chromium-browser')
        expected = str(Path.home() / '.config' / 'chromium')
        assert result == expected

    def test_linux_google_chrome_profile_path(self):
        """On Linux with google-chrome executable, return the Google Chrome profile path."""
        with patch('browser_use.skill_cli.utils.platform.system', return_value='Linux'):
            result = get_chrome_profile_path(None, executable_path='/usr/bin/google-chrome')
        expected = str(Path.home() / '.config' / 'google-chrome')
        assert result == expected

    def test_linux_brave_profile_path(self):
        """On Linux with Brave executable, return Brave's own profile path."""
        with patch('browser_use.skill_cli.utils.platform.system', return_value='Linux'):
            result = get_chrome_profile_path(None, executable_path='/usr/bin/brave-browser')
        expected = str(Path.home() / '.config' / 'BraveSoftware' / 'Brave-Browser')
        assert result == expected

    def test_linux_edge_profile_path(self):
        """On Linux with Microsoft Edge executable, return Edge's own profile path."""
        with patch('browser_use.skill_cli.utils.platform.system', return_value='Linux'):
            result = get_chrome_profile_path(None, executable_path='/usr/bin/microsoft-edge')
        expected = str(Path.home() / '.config' / 'microsoft-edge')
        assert result == expected

    def test_linux_no_executable_path_defaults_to_chrome(self):
        """On Linux with no executable_path, default to Google Chrome profile path."""
        with patch('browser_use.skill_cli.utils.platform.system', return_value='Linux'):
            result = get_chrome_profile_path(None, executable_path=None)
        expected = str(Path.home() / '.config' / 'google-chrome')
        assert result == expected

    def test_macos_profile_path(self):
        """On macOS, return the Chrome Application Support directory."""
        with patch('browser_use.skill_cli.utils.platform.system', return_value='Darwin'):
            result = get_chrome_profile_path(None)
        expected = str(Path.home() / 'Library' / 'Application Support' / 'Google' / 'Chrome')
        assert result == expected

    def test_windows_profile_path(self):
        """On Windows, return the Chrome User Data directory under %LOCALAPPDATA%."""
        import os
        with patch('browser_use.skill_cli.utils.platform.system', return_value='Windows'):
            result = get_chrome_profile_path(None)
        expected = os.path.expandvars(r'%LocalAppData%\Google\Chrome\User Data')
        assert result == expected

    def test_named_profile_returns_profile_name(self):
        """When a profile name is given, return it directly (Chrome uses it as subdirectory)."""
        with patch('browser_use.skill_cli.utils.platform.system', return_value='Linux'):
            result = get_chrome_profile_path('work-profile')
        assert result == 'work-profile'

    def test_named_profile_macos(self):
        """On macOS, named profile returns the profile name directly."""
        with patch('browser_use.skill_cli.utils.platform.system', return_value='Darwin'):
            result = get_chrome_profile_path('my-profile')
        assert result == 'my-profile'
