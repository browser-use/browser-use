"""Regression test: BrowserProfile.user_data_dir must resolve to a temp path both when
explicitly passed as None and when the kwarg is omitted entirely — via get_args(), which
every real launch path calls, but WITHOUT eagerly resolving at construction time.

pydantic v2 skips field_validator for a field left at its default unless the model sets
validate_default=True — without it, BrowserProfile(headless=True) (a very common call
pattern, see e.g. tests/ci/browser/test_screenshot.py) left user_data_dir as raw None
until get_args() resolved it lazily.

Resolving eagerly at construction (e.g. via validate_default=True on the whole
BrowserLaunchPersistentContextArgs config) was tried and reverted: browser_use/browser/
session.py:66 constructs a module-level DEFAULT_BROWSER_PROFILE = BrowserProfile() at
import time, so eager resolution there would make `import browser_use` itself call
tempfile.mkdtemp() — a filesystem side effect on every process start, including for
cloud/CDP-only users who never launch a local browser — and every model_copy() of that
singleton (Agent.__init__, BrowserSession's default_factory) would inherit the exact same
directory instead of getting its own, since model_copy() does not re-run validation.
"""

from browser_use.browser.profile import BrowserProfile


def test_explicit_none_user_data_dir_resolves_to_temp_path_via_get_args():
	profile = BrowserProfile(user_data_dir=None)
	profile.get_args()

	assert profile.user_data_dir is not None
	assert 'browser-use-user-data-dir-' in str(profile.user_data_dir)


def test_omitted_user_data_dir_resolves_to_temp_path_via_get_args():
	profile = BrowserProfile(headless=True)
	profile.get_args()

	assert profile.user_data_dir is not None
	assert 'browser-use-user-data-dir-' in str(profile.user_data_dir)


def test_omitted_and_explicit_none_user_data_dir_are_independently_resolved():
	profile_omitted = BrowserProfile(headless=True)
	profile_explicit = BrowserProfile(headless=True, user_data_dir=None)
	profile_omitted.get_args()
	profile_explicit.get_args()

	assert profile_omitted.user_data_dir is not None
	assert profile_explicit.user_data_dir is not None
	# each construction gets its own freshly generated temp dir
	assert profile_omitted.user_data_dir != profile_explicit.user_data_dir


def test_module_level_default_browser_profile_does_not_eagerly_resolve_user_data_dir():
	"""DEFAULT_BROWSER_PROFILE (browser_use/browser/session.py) is constructed once at module
	import time and must stay side-effect-free — user_data_dir must remain None until
	something actually calls get_args() to launch a browser."""
	from browser_use.browser.session import DEFAULT_BROWSER_PROFILE

	assert DEFAULT_BROWSER_PROFILE.user_data_dir is None


def test_two_default_profile_copies_get_independent_user_data_dirs():
	"""Mirrors Agent.__init__'s `base_profile.model_copy()` fallback when no browser_profile is
	passed (browser_use/agent/service.py) — model_copy() does not re-run field validation, so
	each copy must resolve its own user_data_dir independently once it actually launches."""
	from browser_use.browser.session import DEFAULT_BROWSER_PROFILE

	copy_a = DEFAULT_BROWSER_PROFILE.model_copy()
	copy_b = DEFAULT_BROWSER_PROFILE.model_copy()
	copy_a.get_args()
	copy_b.get_args()

	assert copy_a.user_data_dir != copy_b.user_data_dir
