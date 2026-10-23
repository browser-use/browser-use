"""Managed (throwaway) browser profiles must not reach the OS credential store.

Chromium touches the OS keychain (macOS Keychain, Linux Secret Service) while it
initialises a profile. A browser-use-managed profile is a throwaway temp directory
with nothing to protect and, under headless/CI/containers, no interactive session
to answer the prompt -- Chromium then hangs before opening its CDP port. These
flags keep the managed profile on an in-process mock store, while a
caller-supplied profile keeps real keychain access so saved cookies and passwords
can still be decrypted (the fix from #3225).
"""

import tempfile
from pathlib import Path

from browser_use.browser.profile import BrowserProfile
from browser_use.config import CONFIG

MOCK_KEYCHAIN_ARGS = ('--use-mock-keychain', '--password-store=basic')


def test_default_profile_gets_mock_keychain():
	profile = BrowserProfile(user_data_dir=None, enable_default_extensions=False)

	args = profile.get_args()

	for flag in MOCK_KEYCHAIN_ARGS:
		assert flag in args, f'managed temp profile must pass {flag} to avoid the OS keychain'


def test_explicit_user_profile_keeps_real_keychain():
	user_dir = tempfile.mkdtemp(prefix='chrome-real-profile-')
	profile = BrowserProfile(user_data_dir=user_dir, enable_default_extensions=False)

	args = profile.get_args()

	for flag in MOCK_KEYCHAIN_ARGS:
		assert flag not in args, f'caller-supplied profile must keep real keychain access, but got {flag}'


def test_copied_user_profile_is_not_treated_as_managed():
	"""A real profile is copied into a browser-use temp dir before launch; that copy must still keep real keychain access."""
	user_dir = Path(tempfile.mkdtemp(prefix='chrome-real-profile-')) / 'Default'
	user_dir.mkdir(parents=True, exist_ok=True)
	(user_dir / 'Preferences').write_text('{}')

	profile = BrowserProfile(user_data_dir=user_dir.parent, enable_default_extensions=False)

	# _copy_profile() rewrites user_data_dir to a managed temp copy...
	assert 'browser-use-user-data-dir-' in str(profile.user_data_dir).lower()
	# ...but the decision was taken before the copy, so the flags stay off.
	args = profile.get_args()
	for flag in MOCK_KEYCHAIN_ARGS:
		assert flag not in args, f'copied real profile must keep real keychain access, but got {flag}'


def test_default_config_profile_dir_is_not_managed():
	"""The browser-use persistent default profile is caller-addressable state, not a throwaway dir."""
	profile = BrowserProfile(user_data_dir=CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR, enable_default_extensions=False)

	args = profile.get_args()

	for flag in MOCK_KEYCHAIN_ARGS:
		assert flag not in args, f'persistent default profile must keep real keychain access, but got {flag}'


def test_managed_profile_keeps_mock_keychain_after_temp_fallback():
	"""The launch watchdog retries a failed launch in a `browseruse-tmp-*` dir; that throwaway dir must still avoid the keychain."""
	profile = BrowserProfile(user_data_dir=None, enable_default_extensions=False)

	# Simulate LocalBrowserWatchdog._launch_browser retrying in a fallback temp dir.
	profile.user_data_dir = '/tmp/browseruse-tmp-abc123'

	args = profile.get_args()

	for flag in MOCK_KEYCHAIN_ARGS:
		assert flag in args, f'fallback temp dir must still pass {flag} to avoid the OS keychain'


def test_reassigned_real_profile_dir_drops_mock_keychain():
	"""A profile whose user_data_dir is reassigned to a real Chrome profile after construction must not get the mock flags (see #3225)."""
	profile = BrowserProfile(user_data_dir=None, enable_default_extensions=False)
	assert set(MOCK_KEYCHAIN_ARGS) <= set(profile.get_args())

	profile.user_data_dir = '/home/someone/.config/google-chrome/Default'

	args = profile.get_args()

	for flag in MOCK_KEYCHAIN_ARGS:
		assert flag not in args, f'reassigned real profile must keep real keychain access, but got {flag}'
