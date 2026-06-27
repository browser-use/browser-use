"""Test for verifying error message correctness in Element.click()

This test demonstrates the bug at browser_use/actor/element.py line 347:
- When both CDP click and JS click fail, the error message shows the wrong exception
- Bug: `raise Exception(f'Failed to click element: {e}')` references wrong variable
- Should be: `raise Exception(f'Failed to click element: {js_e}')`
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestElementClickErrorMessage:
	"""Test that Element.click() reports the correct exception in error messages."""

	@pytest.mark.asyncio
	async def test_click_error_reports_js_exception_not_outer(self):
		"""
		Regression test: when both CDP click and JS click fail,
		the error message should show the JS failure (js_e), not the outer CDP failure (e).

		Bug location: browser_use/actor/element.py line 347
		Bug: catches `js_e` but raises with `{e}` (outer exception)
		"""
		from browser_use.actor.element import Element

		# Create a mock browser session
		mock_session = MagicMock()
		mock_client = AsyncMock()  # Use AsyncMock for the CDP client itself
		mock_session.cdp_client = mock_client

		# Create Element instance
		element = Element(
			browser_session=mock_session,
			backend_node_id=123,
			session_id='test-session',
		)

		# First CDP call (scroll into view) fails with outer error
		outer_error_msg = 'OUTER_SCROLL_ERROR'
		mock_client.send.DOM.scrollIntoViewIfNeeded = AsyncMock(side_effect=Exception(outer_error_msg))

		# Second CDP call (resolve node for JS fallback) fails with different error
		js_error_msg = 'INNER_JS_RESOLVE_ERROR'
		mock_client.send.DOM.resolveNode = AsyncMock(side_effect=Exception(js_error_msg))

		# Try to click - should fail
		with pytest.raises(Exception) as exc_info:
			await element.click()

		error_message = str(exc_info.value)

		# THE BUG: Currently line 347 raises with {e} (outer exception)
		# After fix: should raise with {js_e} (actual JS click failure)
		print(f'Error message: {error_message}')
		print(f"Contains outer error '{outer_error_msg}': {outer_error_msg in error_message}")
		print(f"Contains inner error '{js_error_msg}': {js_error_msg in error_message}")

		# This assertion FAILS with the bug, PASSES after fix
		assert js_error_msg in error_message, (
			f'BUG DETECTED: Error message shows wrong exception!\n'
			f"Expected to see JS error: '{js_error_msg}'\n"
			f'But got: {error_message}\n'
			f'This confirms line 347 bug: uses {{e}} instead of {{js_e}}'
		)
