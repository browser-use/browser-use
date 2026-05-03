"""Tests for optional window size management (issue #3303)."""

import tempfile

from browser_use.browser import BrowserProfile, BrowserSession


def test_manage_window_size_default_true():
	"""manage_window_size should default to True."""
	profile = BrowserProfile()
	assert profile.manage_window_size is True


def test_manage_window_size_false_skips_window_size_in_headful():
	"""When manage_window_size=False in headful mode, window_size should not be auto-set."""
	profile = BrowserProfile(headless=False, manage_window_size=False)
	# window_size should remain None since we told it not to manage
	assert profile.window_size is None


def test_manage_window_size_false_omits_chrome_args():
	"""When manage_window_size=False, --window-size and --window-position should not appear in launch args."""
	with tempfile.TemporaryDirectory() as tmpdir:
		profile = BrowserProfile(headless=False, manage_window_size=False, user_data_dir=tmpdir)
		args = profile.get_args()
		arg_str = ' '.join(args)
		assert '--window-size' not in arg_str
		assert '--window-position' not in arg_str
		assert '--start-maximized' not in arg_str


def test_manage_window_size_true_includes_chrome_args():
	"""When manage_window_size=True (default), window args should appear normally."""
	with tempfile.TemporaryDirectory() as tmpdir:
		profile = BrowserProfile(headless=False, manage_window_size=True, user_data_dir=tmpdir)
		args = profile.get_args()
		arg_str = ' '.join(args)
		# Should have either --window-size or --start-maximized
		assert '--window-size' in arg_str or '--start-maximized' in arg_str


def test_manage_window_size_passthrough_via_session():
	"""manage_window_size passed to BrowserSession should propagate to BrowserProfile."""
	session = BrowserSession(manage_window_size=False)
	assert session.browser_profile.manage_window_size is False


def test_manage_window_size_false_still_sets_viewport():
	"""When manage_window_size=False, viewport and screen should still be configured for content rendering."""
	profile = BrowserProfile(headless=True, manage_window_size=False)
	# In headless mode, viewport should still be set for content rendering
	assert profile.viewport is not None
