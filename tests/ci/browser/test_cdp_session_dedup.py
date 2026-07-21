"""Regression tests: startup must create exactly ONE CDP session per pre-existing target.

Root Target.setAutoAttach attaches to all EXISTING related targets as well as future
ones (CDP semantics). _initialize_existing_targets() used to also explicitly call
Target.attachToTarget for every target discovered at startup, so each pre-existing
target ended up with TWO CDP sessions: doubled event streams and monitoring setup,
duplicated lifecycle events in the per-target buffers, and doubled Fetch auth
interception when a proxy is configured. The browser always launches with one
initial tab before the CDP connection is made, so every single startup hit this.
"""

import asyncio

from browser_use.browser.events import NavigateToUrlEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

SIMPLE_HTML = '<html><head><title>page</title></head><body>hello</body></html>'


async def test_startup_creates_exactly_one_session_per_page_target():
	"""The initial tab (a pre-existing target) must have exactly one CDP session after start()."""
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))
	await session.start()
	try:
		session_manager = session.session_manager
		assert session_manager is not None

		page_targets = session_manager.get_all_page_targets()
		assert page_targets, 'expected at least the initial tab as a page target'

		for target in page_targets:
			session_ids = session_manager._target_sessions.get(target.target_id, set())
			assert len(session_ids) == 1, (
				f'target {target.target_id[:8]}... has {len(session_ids)} CDP sessions, expected exactly 1 — '
				f'pre-existing targets must not be attached both explicitly and via root autoAttach'
			)
	finally:
		await session.kill()


async def test_new_tab_after_startup_gets_exactly_one_session(httpserver):
	"""Targets created AFTER startup must still be attached (once) via root autoAttach."""
	httpserver.expect_request('/a').respond_with_data(SIMPLE_HTML, content_type='text/html')
	httpserver.expect_request('/b').respond_with_data(SIMPLE_HTML, content_type='text/html')

	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))
	await session.start()
	try:
		session_manager = session.session_manager
		assert session_manager is not None

		# Occupy the initial tab first so new_tab=True cannot just reuse it
		await session.navigate_to(httpserver.url_for('/a'))
		targets_before = {target.target_id for target in session_manager.get_all_page_targets()}

		event = session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/b'), new_tab=True))
		await event
		await asyncio.sleep(0.5)  # let attach events settle

		page_targets = session_manager.get_all_page_targets()
		new_targets = [target for target in page_targets if target.target_id not in targets_before]
		assert new_targets, 'expected the new tab to appear as a page target'

		for target in page_targets:
			session_ids = session_manager._target_sessions.get(target.target_id, set())
			assert len(session_ids) == 1, (
				f'target {target.target_id[:8]}... has {len(session_ids)} CDP sessions, expected exactly 1'
			)
	finally:
		await session.kill()
