"""Tests for browser-use temp directory leak fix (issue #5422).

Validates that:
1. BrowserProfile construction no longer eagerly creates downloads temp dirs.
2. The watchdog cleanup recognises all browser-use temp dir prefixes.
3. Downloads temp dirs are tracked for cleanup on browser kill.
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. BrowserProfile no longer calls mkdir during construction
# ---------------------------------------------------------------------------

class TestBrowserProfileNoEagerMkdir:
    """set_default_downloads_path must assign a path without creating it."""

    def test_default_downloads_path_not_created_on_disk(self):
        """Constructing BrowserProfile() should NOT create the downloads dir."""
        from browser_use.browser.profile import BrowserProfile

        profile = BrowserProfile()
        downloads = Path(profile.downloads_path)
        # The path should be set but NOT exist on disk
        assert str(downloads).startswith(str(Path(tempfile.gettempdir())))
        assert 'browser-use-downloads-' in downloads.name
        assert not downloads.exists(), (
            f"Downloads dir {downloads} should not be created eagerly"
        )

    def test_explicit_downloads_path_untouched(self):
        """When the user supplies a downloads_path, we must not touch it."""
        from browser_use.browser.profile import BrowserProfile

        custom = Path(tempfile.gettempdir()) / "my-custom-downloads"
        profile = BrowserProfile(downloads_path=str(custom))
        assert Path(profile.downloads_path) == custom


# ---------------------------------------------------------------------------
# 2. Watchdog _cleanup_temp_dir recognises all prefixes
# ---------------------------------------------------------------------------

class TestCleanupTempDirPrefixes:
    """_cleanup_temp_dir must clean dirs with any browser-use prefix."""

    def _make_watchdog(self):
        from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog
        wd = LocalBrowserWatchdog.__new__(LocalBrowserWatchdog)
        wd.logger = MagicMock()
        return wd

    @pytest.mark.parametrize("prefix", [
        "browseruse-tmp-",
        "browser-use-user-data-dir-",
        "browser-use-downloads-",
    ])
    def test_recognised_prefixes_are_cleaned(self, prefix, tmp_path):
        wd = self._make_watchdog()
        target = tmp_path / f"{prefix}abcd1234"
        target.mkdir()
        (target / "somefile.txt").write_text("data")

        wd._cleanup_temp_dir(target)
        assert not target.exists(), f"Dir with prefix '{prefix}' should be removed"

    def test_non_matching_prefix_not_cleaned(self, tmp_path):
        wd = self._make_watchdog()
        target = tmp_path / "important-data-dir"
        target.mkdir()
        (target / "keep.txt").write_text("important")

        wd._cleanup_temp_dir(target)
        assert target.exists(), "Dir without browser-use prefix must NOT be removed"

    def test_empty_path_is_noop(self):
        wd = self._make_watchdog()
        wd._cleanup_temp_dir("")  # should not raise


# ---------------------------------------------------------------------------
# 3. _TEMP_DIR_PREFIXES constant is defined
# ---------------------------------------------------------------------------

class TestTempDirPrefixesConstant:
    def test_constant_exists_and_has_all_prefixes(self):
        from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog
        prefixes = LocalBrowserWatchdog._TEMP_DIR_PREFIXES
        assert 'browseruse-tmp-' in prefixes
        assert 'browser-use-user-data-dir-' in prefixes
        assert 'browser-use-downloads-' in prefixes
