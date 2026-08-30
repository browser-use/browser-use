"""Test that BrowserProfile.get_args() preserves the CHROME_DEFAULT_ARGS ordering.

Regression test for: get_args() converted CHROME_DEFAULT_ARGS to a set when
ignore_default_args was a list, so the remaining default args came back in an
arbitrary order that varied between Python processes (hash-seed dependent).
"""

from browser_use.browser.profile import CHROME_DEFAULT_ARGS, BrowserProfile


def _default_args_in_args_order(profile: BrowserProfile) -> list[str]:
	"""The CHROME_DEFAULT_ARGS entries in the exact order get_args() returned them.

	Iterating ``profile.get_args()`` (not ``CHROME_DEFAULT_ARGS``) keeps the
	actual returned order, so a reordering by get_args() fails the assertions.
	"""
	default_args = set(CHROME_DEFAULT_ARGS)
	return [arg for arg in profile.get_args() if arg in default_args]


def test_get_args_preserves_default_order_with_ignore_list() -> None:
	profile = BrowserProfile(
		ignore_default_args=['--disable-popup-blocking'],
		user_data_dir='/tmp/browser-use-test-profile',
		enable_default_extensions=False,
	)

	args = profile.get_args()

	assert '--disable-popup-blocking' not in args
	expected = [arg for arg in CHROME_DEFAULT_ARGS if arg not in set(profile.ignore_default_args)]
	assert _default_args_in_args_order(profile) == expected


def test_get_args_returns_all_defaults_in_order_without_ignore() -> None:
	profile = BrowserProfile(
		ignore_default_args=[],
		user_data_dir='/tmp/browser-use-test-profile',
		enable_default_extensions=False,
	)

	assert _default_args_in_args_order(profile) == CHROME_DEFAULT_ARGS


def test_get_args_ignores_all_defaults_when_true() -> None:
	profile = BrowserProfile(
		ignore_default_args=True,
		user_data_dir='/tmp/browser-use-test-profile',
		enable_default_extensions=False,
	)

	args = profile.get_args()

	assert not any(arg in args for arg in CHROME_DEFAULT_ARGS)
