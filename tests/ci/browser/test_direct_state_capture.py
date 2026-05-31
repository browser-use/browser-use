from __future__ import annotations

import pytest

from browser_use.browser.events import BrowserStateRequestEvent, ScreenshotEvent


@pytest.mark.asyncio
async def test_browser_state_capture_does_not_dispatch_state_or_screenshot_events(browser_session, httpserver, monkeypatch):
	httpserver.expect_request('/direct-state').respond_with_data(
		"""<!doctype html>
<html>
	<body>
		<button id="answer">Direct state capture</button>
	</body>
</html>""",
		content_type='text/html',
	)

	await browser_session.navigate_to(httpserver.url_for('/direct-state'))

	original_dispatch = browser_session.event_bus.dispatch
	forbidden_event_types = {BrowserStateRequestEvent.__name__, ScreenshotEvent.__name__}

	def guarded_dispatch(event, *args, **kwargs):
		event_type = getattr(event, 'event_type', event.__class__.__name__)
		assert event_type not in forbidden_event_types
		return original_dispatch(event, *args, **kwargs)

	monkeypatch.setattr(browser_session.event_bus, 'dispatch', guarded_dispatch)

	state = await browser_session.get_browser_state_summary(include_screenshot=True)

	assert state.screenshot
	assert state.dom_state is not None
	assert any(node.attributes.get('id') == 'answer' for node in state.dom_state.selector_map.values())
