"""BrowserProfile must not create temp directories until a browser actually launches.

Constructing a profile is cheap and happens in unit tests, imports, and config
plumbing that never launches a browser. Creating a downloads dir eagerly in a
validator leaked one directory per construction into $TMPDIR, forever -- nothing
in the project ever removed them.

DownloadsWatchdog.on_BrowserLaunchEvent() creates the directory when a browser
really starts, so the validator only needs to *assign* the path.
"""

import tempfile
from pathlib import Path

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.watchdogs.local_browser_watchdog import _is_browser_use_temp_dir


def _temp_downloads_dirs() -> set[Path]:
	return set(Path(tempfile.gettempdir()).glob('browser-use-downloads-*'))


def test_construction_does_not_create_downloads_dir() -> None:
	"""A profile that never launches a browser must leave no trace on disk."""
	before = _temp_downloads_dirs()

	profile = BrowserProfile()

	assert profile.downloads_path is not None, 'downloads_path must still be assigned'
	assert _temp_downloads_dirs() == before, 'constructing a BrowserProfile leaked a temp dir'


def test_repeated_construction_does_not_accumulate_dirs() -> None:
	"""The leak was linear in construction count -- guard the whole loop, not one call."""
	before = _temp_downloads_dirs()

	profiles = [BrowserProfile() for _ in range(10)]

	assert len({str(p.downloads_path) for p in profiles}) == 10, 'each profile should get a unique path'
	assert _temp_downloads_dirs() == before, 'repeated construction accumulated temp dirs'


def test_explicit_downloads_path_is_preserved_and_not_created() -> None:
	"""An explicit path is honoured as-is, and still not created ahead of launch."""
	target = Path(tempfile.gettempdir()) / 'browser-use-test-explicit-downloads'
	if target.exists():
		target.rmdir()

	profile = BrowserProfile(downloads_path=target)

	assert Path(profile.downloads_path or '') == target
	assert not target.exists(), 'explicit downloads_path should not be created at construction time'


def test_downloads_path_none_is_replaced_with_a_default() -> None:
	"""Callers gate download tracking on `downloads_path is not None`, so it must stay set."""
	profile = BrowserProfile(downloads_path=None)

	assert profile.downloads_path is not None
	assert 'browser-use-downloads-' in str(profile.downloads_path)


def test_temp_user_data_dir_prefix_is_recognised_for_cleanup() -> None:
	"""Cleanup only matched 'browseruse-tmp-', but get_args() creates 'browser-use-user-data-dir-'.

	The mismatch meant the primary temp profile dir was never deleted on the happy path.
	"""
	assert _is_browser_use_temp_dir(Path(tempfile.gettempdir()) / 'browser-use-user-data-dir-abc123')
	assert _is_browser_use_temp_dir(Path(tempfile.gettempdir()) / 'browseruse-tmp-xyz789')


def test_user_supplied_dirs_are_never_treated_as_temp() -> None:
	"""Deleting a real user profile would be catastrophic -- match on basename only."""
	assert not _is_browser_use_temp_dir(Path.home() / 'my-chrome-profile')
	assert not _is_browser_use_temp_dir(Path(tempfile.gettempdir()) / 'browser-use-downloads-123')
	# a user dir *inside* a matching parent must not match either
	assert not _is_browser_use_temp_dir(Path('/home/me/browser-use-user-data-dir-mine/subdir'))
