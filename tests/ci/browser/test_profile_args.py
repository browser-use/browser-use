from browser_use.browser.profile import CHROME_DEFAULT_ARGS, BrowserProfile


def test_ignore_default_args_preserves_default_order(tmp_path):
	ignored_arg = '--disable-popup-blocking'
	profile = BrowserProfile(
		user_data_dir=tmp_path,
		ignore_default_args=[ignored_arg],
		enable_default_extensions=False,
	)

	expected_default_args = [
		arg for arg in CHROME_DEFAULT_ARGS if arg != ignored_arg and not arg.startswith('--disable-features=')
	]
	actual_args = profile.get_args()
	actual_default_args = [arg for arg in actual_args if arg in expected_default_args]

	assert actual_default_args == expected_default_args
