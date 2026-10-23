import asyncio
"""Test for verifying error message correctness in Element.click()

This test demonstrates the bug at browser_use/actor/element.py line 347:
- When both CDP click and JS click fail, the error message shows the wrong exception
- Bug: `raise Exception(f'Failed to click element: {e}')` references wrong variable
- Should be: `raise Exception(f'Failed to click element: {js_e}')`
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


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


class TestElementClickPressReleaseExceptions:
	"""Regression: press failure must not be replaced by a subsequent release failure."""

	@pytest.mark.asyncio
	async def test_press_failure_not_replaced_by_release_failure(self):
		from browser_use.actor.element import Element

		mock_session = MagicMock()
		mock_client = AsyncMock()
		mock_session.cdp_client = mock_client

		element = Element(
			browser_session=mock_session,
			backend_node_id=123,
			session_id='test-session',
		)

		# Make geometry calls succeed so we reach the mouse events
		mock_client.send.Page.getLayoutMetrics = AsyncMock(return_value={
			'layoutViewport': {'pageX': 0, 'pageY': 0, 'clientWidth': 800, 'clientHeight': 600},
			'visualViewport': {'pageX': 0, 'pageY': 0, 'clientWidth': 800, 'clientHeight': 600, 'offsetX': 0, 'offsetY': 0, 'scale': 1, 'zoom': 1},
			'contentSize': {'x': 0, 'y': 0, 'width': 800, 'height': 600},
			'cssLayoutViewport': {'pageX': 0, 'pageY': 0, 'clientWidth': 800, 'clientHeight': 600},
			'cssVisualViewport': {'pageX': 0, 'pageY': 0, 'clientWidth': 800, 'clientHeight': 600, 'offsetX': 0, 'offsetY': 0, 'scale': 1, 'zoom': 1},
			'cssContentSize': {'x': 0, 'y': 0, 'width': 800, 'height': 600},
		})
		mock_client.send.DOM.getContentQuads = AsyncMock(return_value={
			'quads': [[10, 10, 20, 10, 20, 20, 10, 20]]
		})
		mock_client.send.DOM.scrollIntoViewIfNeeded = AsyncMock()
		mock_client.send.Input.dispatchMouseEvent = AsyncMock()

		# mousePressed times out / fails
		async def dispatch_side_effect(params, session_id=None):
			if params.get('type') == 'mousePressed':
				raise asyncio.TimeoutError('press timed out')
			if params.get('type') == 'mouseReleased':
				raise ConnectionError('WebSocket connection closed')
			return {}

		mock_client.send.Input.dispatchMouseEvent.side_effect = dispatch_side_effect

		with pytest.raises(RuntimeError) as exc_info:
			await element.click()

		err = str(exc_info.value)
		assert 'TimeoutError' in err or 'press timed out' in err, f'Press failure was replaced: {err}'
		# Release error should not be the primary message
		assert 'ConnectionError' not in err or 'TimeoutError' in err
