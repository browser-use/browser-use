"""Regression test: a failed ScrollEvent dispatch must not be reported as a successful scroll.

Prior to the fix, `scroll()`'s pages>=1.0 branch caught every per-attempt exception,
logged a warning, and then unconditionally returned a success ActionResult (with a
hardcoded "Scrolled down {viewport_height}px" message for the default pages=1.0 case),
even when zero scroll attempts actually completed.
"""

from browser_use.tools.service import Tools
from browser_use.tools.views import ScrollAction


async def test_scroll_returns_error_when_no_active_target(browser_session):
	"""`on_ScrollEvent` raises BrowserError('No active target for scrolling') when
	`agent_focus_target_id` is unset — a real failure condition, not a mock — and
	`scroll()` must surface that as an error, not a fabricated success message.
	"""
	tools = Tools()
	ActionModel = tools.registry.create_action_model()
	action = ActionModel(**{'scroll': ScrollAction(down=True).model_dump()})

	original_target_id = browser_session.agent_focus_target_id
	browser_session.agent_focus_target_id = None
	try:
		result = await tools.act(action, browser_session=browser_session)
	finally:
		browser_session.agent_focus_target_id = original_target_id

	assert result.error is not None, (
		f'scroll() reported success ({result.extracted_content!r}) despite every scroll attempt failing'
	)
	assert 'Scrolled' not in (result.extracted_content or ''), (
		f'scroll() fabricated a success message despite failing: {result.extracted_content!r}'
	)
