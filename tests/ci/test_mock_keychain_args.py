"""Test that --use-mock-keychain and --password-store=basic are added only for browser-use-managed profiles.

When browser-use creates a temporary profile directory (user_data_dir not supplied),
these flags should be present to avoid OS keychain prompts/hangs. When the user
explicitly supplies their own user_data_dir, the flags must be omitted so that
real keychain access is preserved for cookie/password decryption.

See: https://github.com/browser-use/browser-use/issues/5415
"""

import tempfile

from browser_use.browser.profile import BrowserProfile

MOCK_KEYCHAIN_FLAGS = ('--use-mock-keychain', '--password-store=basic')


class TestMockKeychainArgs:
	"""Verify mock-keychain flags are applied conditionally based on profile type."""

	def test_default_profile_includes_mock_keychain(self):
		"""Default BrowserProfile (no user_data_dir) should include mock keychain args."""
		profile = BrowserProfile(user_data_dir=None)
		args = profile.get_args()

		for flag in MOCK_KEYCHAIN_FLAGS:
			assert flag in args, (
				f'Expected {flag} in args for default (managed) profile, but it was missing. '
				f'Managed profiles should use mock keychain to avoid OS keychain prompts.'
			)

	def test_explicit_user_data_dir_excludes_mock_keychain(self):
		"""BrowserProfile with explicit user_data_dir should NOT include mock keychain args."""
		user_dir = tempfile.mkdtemp(prefix='test-user-profile-')
		profile = BrowserProfile(user_data_dir=user_dir)
		args = profile.get_args()

		for flag in MOCK_KEYCHAIN_FLAGS:
			assert flag not in args, (
				f'Expected {flag} NOT in args for user-supplied profile, but it was present. '
				f'User-supplied profiles need real keychain access for cookie/password decryption.'
			)

	def test_user_data_dir_none_includes_mock_keychain(self):
		"""BrowserProfile(user_data_dir=None) should include mock keychain args (same as default)."""
		profile = BrowserProfile(user_data_dir=None)
		args = profile.get_args()

		for flag in MOCK_KEYCHAIN_FLAGS:
			assert flag in args, (
				f'Expected {flag} in args when user_data_dir=None, but it was missing. '
				f'None means browser-use should manage the profile with mock keychain.'
			)
