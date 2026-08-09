"""Tests for BrowserProfile.use_system_keychain and its effect on get_args()."""

from browser_use.browser.profile import CONFIG, BrowserChannel, BrowserProfile


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


def test_real_chrome_profile_keeps_system_keychain_after_copy_profile_rewrites_user_data_dir(tmp_path):
	"""use_system_keychain must be decided from the ORIGINAL real user_data_dir before _copy_profile()
	rewrites it to a browser-use-managed-looking temp dir — and must stay True afterward, so a copied
	real Chrome profile's OS-keychain-encrypted cookies/passwords stay decryptable. The path here has
	no 'chrome' substring and channel=CHROME is what makes _copy_profile() actually perform the copy
	(is_chrome True), unlike test_real_user_supplied_profile_keeps_system_keychain_by_default's path,
	which has no 'chrome' substring/executable_path/CHROME channel and so never exercises the copy."""
	real_profile_dir = tmp_path / 'my-real-profile'
	real_profile_dir.mkdir()

	profile = BrowserProfile(user_data_dir=real_profile_dir, channel=BrowserChannel.CHROME)

	# _copy_profile() must have actually rewritten user_data_dir to a temp copy (proving the copy ran).
	assert str(profile.user_data_dir) != str(real_profile_dir)
	assert 'browser-use-user-data-dir-' in str(profile.user_data_dir).lower()

	args = profile.get_args()
	assert '--use-mock-keychain' not in args
	assert '--password-store=basic' not in args


def test_default_browser_use_profile_avoids_system_keychain_with_non_default_channel():
	"""Pins an ordering dependency: model_post_init resolves use_system_keychain BEFORE the
	model_validator(mode='after') warn_user_data_dir_non_default_version rewrites a user_data_dir
	equal to CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR to a sibling '.../default-{channel}' dir (only
	triggered by a non-default channel — test_default_browser_use_profile_avoids_system_keychain_by_default
	uses the default channel, so that rewrite validator never fires there and this ordering goes
	unexercised). If model_post_init ever ran after that rewrite, the sibling path would match neither
	the None check, the temp-dir substring, nor an exact equal to BROWSER_USE_DEFAULT_USER_DATA_DIR, so
	use_system_keychain would flip to True — silently reintroducing OS keychain prompts for a
	browser-use-managed profile."""
	profile = BrowserProfile(user_data_dir=CONFIG.BROWSER_USE_DEFAULT_USER_DATA_DIR, channel=BrowserChannel.CHROME)
	args = profile.get_args()

	assert profile.use_system_keychain is False
	assert '--use-mock-keychain' in args
	assert '--password-store=basic' in args


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
