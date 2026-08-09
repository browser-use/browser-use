"""Regression tests for temp dir leaks in $TMPDIR.

Repro that motivated this file (see the linked issue): constructing a BrowserProfile alone -
without ever launching a browser - created a `browser-use-downloads-*` dir on disk via a
model_validator, and `get_args()` created a `browser-use-user-data-dir-*` dir that
LocalBrowserWatchdog's cleanup could never remove (its cleanup only matched the
'browseruse-tmp-' prefix used by SingletonLock retries, never the 'browser-use-user-data-dir-'
prefix BrowserProfile itself creates). A clean start()+kill() cycle leaked all 3 dirs it
created. Measured on a real machine: 36 purely-unit tests (no browser ever launched) leaked 14
dirs, accumulating to 7741 dirs / 14GB in $TMPDIR over time.

Fix: BrowserProfile no longer creates the downloads dir eagerly (DownloadsWatchdog creates it
lazily on BrowserLaunchEvent, same as it always has); LocalBrowserWatchdog's cleanup now also
recognizes 'browser-use-user-data-dir-' as its own; DownloadsWatchdog removes its downloads dir
on BrowserStoppedEvent if left empty; and an atexit safety net sweeps anything that never made
it through the normal cleanup path (Ctrl-C, a test killed by pytest --timeout).

Also covered: BrowserSession(...) construction (any form, since it always builds a BrowserProfile
internally) triggers pydantic to revalidate the profile as part of assigning it to
BrowserSession.browser_profile. That revalidation re-runs
BrowserLaunchPersistentContextArgs.validate_user_data_dir (a field_validator, mode='after') even
though the field was never explicitly passed - pydantic only skips field_validator for a field left
at its default on *first* construction, not on revalidation of an existing instance (verified with
an isolated pydantic model). So this DOES create a temp user_data_dir on disk immediately - earlier
than the otherwise-lazy get_args() path. If the session's start()/kill() lifecycle runs,
LocalBrowserWatchdog's cleanup (fixed above) removes it as usual; for the case where a session is
constructed and discarded without ever starting/killing it (e.g. a unit test that only inspects
`session.browser_profile.some_field`), the dir is registered with the same atexit safety net so it
still doesn't survive process exit permanently. Deliberately not touching validate_user_data_dir's
semantics itself (e.g. leaving user_data_dir as None) - browser_use/browser/session.py's
StorageStateWatchdog auto-enable logic reads `browser_profile.user_data_dir is not None` before
get_args() ever runs, so changing what that field observes at revalidation time would be a
behavior change beyond this leak fix.
"""

import glob
import os
import tempfile
from pathlib import Path

import pytest


def _snapshot_browser_use_temp_dirs() -> set[str]:
	return set(glob.glob(os.path.join(tempfile.gettempdir(), 'browser-use-*')))


def test_constructing_a_profile_creates_no_files_on_disk():
	"""Repro 1: BrowserProfile() alone, browser never launched, must not touch the filesystem."""
	before = _snapshot_browser_use_temp_dirs()

	from browser_use.browser.profile import BrowserProfile

	profile = BrowserProfile()

	# downloads_path must still be assigned (agent/service.py and beta/service.py gate download
	# tracking on `downloads_path is not None`), just not materialized on disk yet.
	assert profile.downloads_path is not None
	assert not Path(profile.downloads_path).exists()

	after = _snapshot_browser_use_temp_dirs()
	assert after == before, f'BrowserProfile() leaked: {after - before}'


def test_get_args_creates_user_data_dir_but_not_downloads_dir():
	"""get_args() (called by every real launch path) must resolve user_data_dir lazily, same as
	before, but still must not touch downloads_path - that stays DownloadsWatchdog's job."""
	before = _snapshot_browser_use_temp_dirs()

	from browser_use.browser.profile import BrowserProfile

	profile = BrowserProfile()
	profile.get_args()

	assert profile.user_data_dir is not None
	assert Path(profile.user_data_dir).exists()
	assert not Path(profile.downloads_path).exists()  # type: ignore[arg-type]

	after = _snapshot_browser_use_temp_dirs()
	created = {str(Path(p).resolve()) for p in after - before}
	# macOS symlinks /var -> /private/var, so resolve() before comparing paths from different sources.
	assert created == {str(Path(profile.user_data_dir).resolve())}, f'unexpected dirs created: {after - before}'


def test_default_browser_profile_singleton_creates_no_files_on_disk():
	"""DEFAULT_BROWSER_PROFILE (browser_use/browser/session.py:66) is constructed at import time -
	must not leak a downloads dir on every `import browser_use.browser`."""
	from browser_use.browser.session import DEFAULT_BROWSER_PROFILE

	assert DEFAULT_BROWSER_PROFILE.downloads_path is not None
	assert not Path(DEFAULT_BROWSER_PROFILE.downloads_path).exists()


async def test_clean_start_and_kill_leaves_no_temp_dirs():
	"""Repro 2: the only test here that actually launches a browser. A fully clean start()+kill()
	cycle, no errors, no interruption, must leave $TMPDIR exactly as it found it."""
	before = _snapshot_browser_use_temp_dirs()

	from browser_use.browser import BrowserSession

	session = BrowserSession(headless=True)
	await session.start()
	created = _snapshot_browser_use_temp_dirs() - before
	assert created, 'expected start() to create at least a user_data_dir for the assertions below to be meaningful'

	await session.kill()

	after = _snapshot_browser_use_temp_dirs()
	assert after == before, f'clean start()+kill() leaked: {after - before}'


async def test_downloads_dir_with_files_is_not_deleted_on_stop():
	"""Regression: the empty-dir cleanup on BrowserStoppedEvent must never delete a downloads dir
	that actually has files in it."""
	from browser_use.browser import BrowserSession

	session = BrowserSession(headless=True)
	await session.start()

	downloads_path = Path(session.browser_profile.downloads_path)  # type: ignore[arg-type]
	downloads_path.mkdir(parents=True, exist_ok=True)
	(downloads_path / 'definitely-not-garbage.txt').write_text('kept')

	await session.kill()

	assert downloads_path.exists(), 'a non-empty downloads dir must survive cleanup'
	assert (downloads_path / 'definitely-not-garbage.txt').exists()

	# manual cleanup since this test intentionally defeats the auto-cleanup
	import shutil

	shutil.rmtree(downloads_path, ignore_errors=True)


def test_user_supplied_user_data_dir_is_never_deleted():
	"""Regression: LocalBrowserWatchdog._cleanup_temp_dir() must refuse to remove a user-supplied
	user_data_dir - only paths carrying the 'browseruse-tmp-' or 'browser-use-user-data-dir-'
	prefixes we generate ourselves are ever eligible for deletion.

	Exercises the cleanup helper directly rather than a full browser launch - the launch path is
	covered by test_clean_start_and_kill_leaves_no_temp_dirs above, and this is the one place a
	user's own profile directory could get silently deleted, so it's worth pinning down in
	isolation from browser startup flakiness.
	"""
	from browser_use.browser import BrowserSession
	from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog

	# Constructing a BrowserSession/watchdog does not launch a browser - only .start() does - so this
	# stays fast and isolated from the browser-startup flakiness that test_clean_start_and_kill_leaves_no_temp_dirs
	# and test_downloads_dir_with_files_is_not_deleted_on_stop already cover with a real launch.
	session = BrowserSession(headless=True)
	watchdog = LocalBrowserWatchdog(browser_session=session, event_bus=session.event_bus)

	with tempfile.TemporaryDirectory(prefix='my-own-user-profile-') as user_dir:
		watchdog._cleanup_temp_dir(user_dir)
		assert Path(user_dir).exists(), 'a user-supplied user_data_dir must survive cleanup'


def test_owned_temp_dir_prefixes_are_deleted():
	"""Regression: the flip side of the above - both prefixes BrowserProfile/LocalBrowserWatchdog
	actually generate themselves must still be recognized and removed."""
	from browser_use.browser import BrowserSession
	from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog

	session = BrowserSession(headless=True)
	watchdog = LocalBrowserWatchdog(browser_session=session, event_bus=session.event_bus)
	for prefix in ('browseruse-tmp-', 'browser-use-user-data-dir-'):
		owned_dir = tempfile.mkdtemp(prefix=prefix)
		watchdog._cleanup_temp_dir(owned_dir)
		assert not Path(owned_dir).exists(), f'{prefix} dir should have been cleaned up'


def test_revalidated_profile_user_data_dir_is_registered_for_atexit_cleanup():
	"""Regression: BrowserSession(...) construction revalidates the profile it builds internally
	(BrowserProfile has revalidate_instances='always'), which re-runs validate_user_data_dir and
	creates a user_data_dir immediately - earlier than the lazy get_args() path. This dir must at
	least be tracked by the atexit safety net, even though it isn't synchronously cleaned up here
	(no start()/kill() was called - see the module docstring for why we don't change
	validate_user_data_dir's observable None-vs-resolved semantics to avoid this eager creation)."""
	from browser_use.browser import BrowserSession
	from browser_use.browser.profile import _owned_temp_dirs_registry

	session = BrowserSession(headless=True)
	user_data_dir = str(session.browser_profile.user_data_dir)

	assert user_data_dir in _owned_temp_dirs_registry, (
		'the eagerly-created user_data_dir from profile revalidation must be tracked for atexit cleanup'
	)


@pytest.mark.parametrize('leaked_run_index', range(3))
async def test_repeated_profile_construction_does_not_accumulate_dirs(leaked_run_index: int):
	"""Repro 3 (condensed): constructing profiles in a loop without ever launching a browser -
	the exact pattern of a pure-unit test suite - must not accumulate any dirs at all."""
	before = _snapshot_browser_use_temp_dirs()

	from browser_use.browser.profile import BrowserProfile

	for _ in range(5):
		BrowserProfile()

	after = _snapshot_browser_use_temp_dirs()
	assert after == before, f'leaked {len(after - before)} dirs from plain construction: {after - before}'
