"""
Test SessionManager.get_all_page_targets() target filtering.

Regression test for #4133: extension side panels are reported by CDP as
type='page' targets with chrome-extension:// URLs. They must NOT be returned
by get_all_page_targets(), otherwise crash-recovery focus, the tab list shown
to the LLM, and initial connect can all switch the agent into the extension
window.

Usage:
	uv run pytest tests/ci/browser/test_session_manager_targets.py -v -s
"""

from browser_use.browser.session import Target
from browser_use.browser.session_manager import SessionManager


def _make_manager(*targets: Target) -> SessionManager:
	"""Build a SessionManager without a BrowserSession.

	get_all_page_targets() only reads self._targets, so we bypass the
	browser-dependent __init__ and populate the owned target dict directly
	with real Target objects (no mocking of behavior).
	"""
	mgr = SessionManager.__new__(SessionManager)
	mgr._targets = {t.target_id: t for t in targets}
	return mgr


def test_extension_side_panel_excluded():
	"""chrome-extension:// targets with type='page' must be filtered out."""
	page = Target(target_id='t-page', target_type='page', url='https://example.com/')
	side_panel = Target(
		target_id='t-ext',
		target_type='page',
		url='chrome-extension://abcdefghijklmnop/sidepanel.html',
	)
	mgr = _make_manager(page, side_panel)

	result = mgr.get_all_page_targets()

	assert page in result
	assert side_panel not in result
	assert [t.target_id for t in result] == ['t-page']


def test_regular_pages_and_tabs_still_returned():
	"""Non-extension page/tab targets are unaffected by the filter."""
	http_page = Target(target_id='t1', target_type='page', url='https://example.com/')
	blank_page = Target(target_id='t2', target_type='page', url='about:blank')
	tab = Target(target_id='t3', target_type='tab', url='http://localhost:8000/')
	worker = Target(target_id='t4', target_type='service_worker', url='https://example.com/sw.js')
	mgr = _make_manager(http_page, blank_page, tab, worker)

	result = mgr.get_all_page_targets()

	# worker is excluded by target_type as before; the three page/tab targets remain
	assert {t.target_id for t in result} == {'t1', 't2', 't3'}


def test_include_chrome_extensions_opt_in():
	"""Extension-cleanup code can opt in to see chrome-extension:// targets.

	_close_extension_options_pages() relies on this to find and close extension
	options/onboarding pages, so the opt-in must surface them.
	"""
	page = Target(target_id='t-page', target_type='page', url='https://example.com/')
	options_page = Target(
		target_id='t-opt',
		target_type='page',
		url='chrome-extension://abcdefghijklmnop/options.html',
	)
	mgr = _make_manager(page, options_page)

	assert options_page not in mgr.get_all_page_targets()
	assert options_page in mgr.get_all_page_targets(include_chrome_extensions=True)
	assert page in mgr.get_all_page_targets(include_chrome_extensions=True)
