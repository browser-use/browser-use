"""Tests for BrowserProfile.use_system_keychain and its effect on get_args()."""

from browser_use.browser.profile import CONFIG, BrowserProfile


def test_temporary_profile_avoids_system_keychain_by_default():
	profile = BrowserProfile(user_data_dir=None)
	args = profile.get_args()

	assert '--use-mock-keychain' in args
	assert '--password-store=basic' in args


def test_default_browser_use_profile_avoids_system_keychain_by_default():
	profile = BrowserProfile(headless=True, user_data_dir=CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR, keep_alive=False)
	args = profile.get_args()

	assert '--use-mock-keychain' in args
	assert '--password-store=basic' in args


def test_real_user_supplied_profile_keeps_system_keychain_by_default(tmp_path):
	profile = BrowserProfile(user_data_dir=tmp_path / 'my-real-profile')
	args = profile.get_args()

	assert '--use-mock-keychain' not in args
	assert '--password-store=basic' not in args


def test_explicit_use_system_keychain_true_overrides_temporary_profile_default():
	profile = BrowserProfile(user_data_dir=None, use_system_keychain=True)
	args = profile.get_args()

	assert '--use-mock-keychain' not in args
	assert '--password-store=basic' not in args


def test_explicit_use_system_keychain_false_overrides_real_profile_default(tmp_path):
	profile = BrowserProfile(user_data_dir=tmp_path / 'my-real-profile', use_system_keychain=False)
	args = profile.get_args()

	assert '--use-mock-keychain' in args
	assert '--password-store=basic' in args


def test_omitted_user_data_dir_still_avoids_system_keychain():
	"""use_system_keychain's auto-detection must not rely on user_data_dir's field_validator having
	already run (see #5414) — BrowserProfile(headless=True) with no explicit user_data_dir= is a very
	common call pattern and must not be treated as a real user profile."""
	profile = BrowserProfile(headless=True)

	assert profile.use_system_keychain is False
