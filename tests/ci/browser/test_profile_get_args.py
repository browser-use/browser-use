"""Regression test for https://github.com/browser-use/browser-use/issues/5397

BrowserProfile.get_args() converted CHROME_DEFAULT_ARGS to a `set` when
ignore_default_args was passed as a list, so the order of the remaining
default args depended on Python's per-process string hash seed instead of
their declared order in CHROME_DEFAULT_ARGS.
"""

from browser_use.browser.profile import CHROME_DEFAULT_ARGS, BrowserProfile


def _extract_default_args(profile_args: list[str], ignored: set[str]) -> list[str]:
	"""The subset of profile_args that came from CHROME_DEFAULT_ARGS, in the order returned."""
	default_arg_set = set(CHROME_DEFAULT_ARGS) - ignored
	return [arg for arg in profile_args if arg in default_arg_set]


def test_ignore_default_args_preserves_declared_order():
	"""Removing an entry from CHROME_DEFAULT_ARGS via ignore_default_args must not
	reorder the remaining entries. The old implementation went through `set(...)
	- set(...)`, whose iteration order depends on Python's per-process string hash
	seed rather than the declared order of CHROME_DEFAULT_ARGS -- for a list this
	long, a hash-seed-dependent ordering would essentially never match the
	declared order by chance, so this assertion reliably catches the regression."""
	ignored = ['--disable-popup-blocking']
	profile = BrowserProfile(user_data_dir='/tmp/browser-use-test-profile', ignore_default_args=ignored)

	args = profile.get_args()

	assert '--disable-popup-blocking' not in args

	remaining_defaults = _extract_default_args(args, set(ignored))
	expected_order = [arg for arg in CHROME_DEFAULT_ARGS if arg not in set(ignored)]
	assert remaining_defaults == expected_order
