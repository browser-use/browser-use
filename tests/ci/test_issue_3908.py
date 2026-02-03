import asyncio

import pytest

from browser_use.browser.events import BrowserStartEvent
from browser_use.browser.session import BrowserSession


@pytest.mark.asyncio
async def test_reproduce_create_target_no_browser_failure():
	"""
	Reproduction for Issue #3908:
	Closing all pages results in 'Target.createTarget' failure with newWindow=False
	because no window exists.
	"""
	# Create session (this starts the browser if local)
	session = BrowserSession()

	try:
		# Start session explicitly (if needed, though operations usually autostart)
		# However, we need access to session_manager to get targets.
		context = await session.on_BrowserStartEvent(BrowserStartEvent())

		# Ensure we have at least one page
		page_targets = session.session_manager.get_all_page_targets()
		assert len(page_targets) > 0, 'Should have started with at least one page'

		# Close ALL pages
		for target in page_targets:
			await session._cdp_close_page(target.target_id)

		# Give a moment for browser state to update
		# Polling wait for pages to close
		for _ in range(20):
			page_targets_now = session.session_manager.get_all_page_targets()
			if len(page_targets_now) == 0:
				break
			await asyncio.sleep(0.1)

		page_targets_now = session.session_manager.get_all_page_targets()
		assert len(page_targets_now) == 0, f'All pages should be closed, but found {len(page_targets_now)}'

		# Now try to create a new page with new_window=False (default behavior in session.py)
		# This SHOULD fail prior to fix, and PASS after fix.
		# We call _cdp_create_new_page directly as it's the internal method failing
		new_target_id = await session._cdp_create_new_page(url='about:blank', new_window=False)

		# If we reach here, it succeeded
		assert new_target_id is not None

	finally:
		await session.stop()
