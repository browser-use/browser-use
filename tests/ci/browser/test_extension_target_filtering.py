"""Regression test for https://github.com/browser-use/browser-use/issues/4133

SessionManager.get_all_page_targets() filtered targets by CDP target_type only,
so a chrome-extension:// page (a side panel, an options page, or a popup opened
as its own tab) passed straight through as a normal "page"/"tab" target. That
target then leaked into BrowserSession.get_tabs() -- the "Available tabs" list
shown to the LLM -- and into crash-recovery focus selection, so the agent could
end up believing it was looking at, or switch its own focus to, an internal
extension surface instead of a real page.

BrowserSession._is_valid_target() already excludes chrome-extension:// URLs by
default (include_chrome_extensions=False) for every other target-discovery path
in the codebase; get_all_page_targets() was the one path missing that filter.
"""

from browser_use.browser.session import BrowserSession, Target
from browser_use.browser.session_manager import SessionManager


def _make_session_manager() -> SessionManager:
	# BrowserSession() with no cdp_url/executable just builds the object and its
	# attributes -- it does not launch or connect to a browser.
	session = BrowserSession()
	return SessionManager(session)


def test_get_all_page_targets_excludes_chrome_extension_pages():
	manager = _make_session_manager()

	real_page = Target(target_id='PAGE1', target_type='page', url='https://example.com/', title='Example')
	extension_page = Target(
		target_id='EXT1',
		target_type='page',
		url='chrome-extension://abcdefghijklmnopabcdefghijklmnop/panel.html',
		title='Extension Panel',
	)
	manager._targets[real_page.target_id] = real_page
	manager._targets[extension_page.target_id] = extension_page

	page_targets = manager.get_all_page_targets()

	assert page_targets == [real_page]


async def test_get_tabs_excludes_chrome_extension_pages():
	session = BrowserSession()
	session.session_manager = SessionManager(session)

	real_page = Target(target_id='PAGE1', target_type='page', url='https://example.com/', title='Example')
	extension_page = Target(
		target_id='EXT1',
		target_type='tab',
		url='chrome-extension://abcdefghijklmnopabcdefghijklmnop/panel.html',
		title='Extension Panel',
	)
	session.session_manager._targets[real_page.target_id] = real_page
	session.session_manager._targets[extension_page.target_id] = extension_page

	tabs = await session.get_tabs()

	assert [tab.url for tab in tabs] == ['https://example.com/']
