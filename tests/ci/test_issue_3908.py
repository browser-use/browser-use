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
		# Polling wait for pages to update (close or auto-recover)
		for _ in range(50):
			page_targets_now = session.session_manager.get_all_page_targets()
			# We are stable if we have pages (auto-recovered) OR if we verified 0 pages long enough
			# But simpler: just wait a bit and see state.
			if len(page_targets_now) > 0:
				break
			await asyncio.sleep(0.1)

		page_targets_now = session.session_manager.get_all_page_targets()

		# If auto-recovery happened (using our fix), we have pages.
		# If not, we try to create one manually to verify the fix works in '0 pages' state.
		if len(page_targets_now) == 0:
			await session._cdp_create_new_page(url='about:blank', new_window=False)
			page_targets_now = session.session_manager.get_all_page_targets()

		# The fix is verified if we have pages now and didn't crash with "no browser is open"
		assert len(page_targets_now) > 0, f'Should have active pages (recovered or created), but found {len(page_targets_now)}'

	finally:
		await session.stop()
