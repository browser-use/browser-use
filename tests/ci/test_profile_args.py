import pytest

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


def test_get_args_merges_user_load_extension_with_default_extensions(tmp_path, monkeypatch: pytest.MonkeyPatch):
	"""A user-provided --load-extension must not be overwritten by the default extensions' --load-extension."""
	default_ext_paths = ['/cache/ub-origin', '/cache/cookie-ext']
	monkeypatch.setattr(BrowserProfile, '_ensure_default_extensions_downloaded', lambda self: default_ext_paths)

	profile = BrowserProfile(
		user_data_dir=tmp_path,
		args=['--load-extension=/my/custom/ext'],
		enable_default_extensions=True,
	)

	args = profile.get_args()

	load_extension_args = [arg for arg in args if arg.startswith('--load-extension')]
	assert len(load_extension_args) == 1
	paths = load_extension_args[0].split('=', 1)[1].split(',')
	assert '/my/custom/ext' in paths
	assert '/cache/ub-origin' in paths
	assert '/cache/cookie-ext' in paths


def test_get_args_keeps_user_load_extension_without_default_extensions(tmp_path, monkeypatch: pytest.MonkeyPatch):
	"""With default extensions disabled, the user-provided --load-extension must pass through unchanged."""
	monkeypatch.setattr(BrowserProfile, '_ensure_default_extensions_downloaded', lambda self: ['/cache/ub-origin'])

	profile = BrowserProfile(
		user_data_dir=tmp_path,
		args=['--load-extension=/my/custom/ext'],
		enable_default_extensions=False,
	)

	args = profile.get_args()

	assert '--load-extension=/my/custom/ext' in args


def test_get_args_dedupes_load_extension_paths(tmp_path, monkeypatch: pytest.MonkeyPatch):
	"""Duplicate --load-extension paths (user + defaults) are merged into one arg without repetition."""
	default_ext_paths = ['/cache/ub-origin', '/my/custom/ext']
	monkeypatch.setattr(BrowserProfile, '_ensure_default_extensions_downloaded', lambda self: default_ext_paths)

	profile = BrowserProfile(
		user_data_dir=tmp_path,
		args=['--load-extension=/my/custom/ext', '--load-extension=/other/ext'],
		enable_default_extensions=True,
	)

	args = profile.get_args()

	load_extension_args = [arg for arg in args if arg.startswith('--load-extension')]
	assert load_extension_args == ['--load-extension=/my/custom/ext,/other/ext,/cache/ub-origin']
