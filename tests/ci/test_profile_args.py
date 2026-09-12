from browser_use.browser.profile import CHROME_DEFAULT_ARGS, BrowserProfile


def test_get_args_keeps_default_order_when_ignoring_default_args(tmp_path):
	profile = BrowserProfile(
		user_data_dir=tmp_path,
		ignore_default_args=['--disable-popup-blocking', '--no-default-browser-check'],
		enable_default_extensions=False,
	)

	args = profile.get_args()

	expected_defaults = [
		arg for arg in CHROME_DEFAULT_ARGS if arg not in {'--disable-popup-blocking', '--no-default-browser-check'}
	]
	actual_defaults = [arg for arg in args if arg in CHROME_DEFAULT_ARGS]

	assert actual_defaults == expected_defaults
	assert '--disable-popup-blocking' not in args
	assert '--no-default-browser-check' not in args


def test_get_args_keeps_default_order_with_default_ignored_args(tmp_path):
	profile = BrowserProfile(user_data_dir=tmp_path, enable_default_extensions=False)

	args = profile.get_args()

	ignored_default_args = profile.ignore_default_args if isinstance(profile.ignore_default_args, list) else []
	expected_defaults = [arg for arg in CHROME_DEFAULT_ARGS if arg not in ignored_default_args]
	actual_defaults = [arg for arg in args if arg in CHROME_DEFAULT_ARGS]

	assert actual_defaults == expected_defaults
