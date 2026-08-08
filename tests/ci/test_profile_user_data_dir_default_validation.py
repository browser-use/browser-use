"""Regression test: BrowserProfile.user_data_dir must resolve to a temp path both when
explicitly passed as None and when the kwarg is omitted entirely.

pydantic v2 skips field_validator for a field left at its default unless the model sets
validate_default=True — without it, BrowserProfile(headless=True) (a very common call
pattern, see e.g. tests/ci/browser/test_screenshot.py) left user_data_dir as raw None.
"""

from browser_use.browser.profile import BrowserProfile


def test_explicit_none_user_data_dir_resolves_to_temp_path():
	profile = BrowserProfile(user_data_dir=None)

	assert profile.user_data_dir is not None
	assert 'browser-use-user-data-dir-' in str(profile.user_data_dir)


def test_omitted_user_data_dir_resolves_to_temp_path():
	profile = BrowserProfile(headless=True)

	assert profile.user_data_dir is not None
	assert 'browser-use-user-data-dir-' in str(profile.user_data_dir)


def test_omitted_and_explicit_none_user_data_dir_are_independently_resolved():
	profile_omitted = BrowserProfile(headless=True)
	profile_explicit = BrowserProfile(headless=True, user_data_dir=None)

	assert profile_omitted.user_data_dir is not None
	assert profile_explicit.user_data_dir is not None
	# each construction gets its own freshly generated temp dir
	assert profile_omitted.user_data_dir != profile_explicit.user_data_dir
