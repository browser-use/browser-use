"""Regression test: clicks on same-origin iframe elements must use real mouse events.

The occlusion pre-check runs in the element's own JS realm, where elementFromPoint
expects frame-local coordinates. Probing with top-viewport coordinates misclassifies
every iframe element as occluded, downgrading the click to a JS this.click() fallback
that fires no mousedown/mouseup. A real CDP mouse click fires mousedown — that is the
observable this test asserts on.
"""

import asyncio

import pytest

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.tools.service import Tools

IFRAME_HTML = """
<!DOCTYPE html>
<html>
<body style="margin: 0;">
	<div style="height: 120px;">spacer inside iframe</div>
	<button id="iframe-button"
		onmousedown="parent.document.title = 'mousedown-received'"
		onclick="if (parent.document.title !== 'mousedown-received') parent.document.title = 'click-only'">
		Click me
	</button>
	<!-- Non-ancestor element occupying the spot where the button's TOP-VIEWPORT
	     coordinates land inside this frame's local space. A wrong-realm probe hits
	     this instead of the button and misclassifies the button as occluded. -->
	<div id="decoy" style="height: 300px;">decoy content below the button</div>
</body>
</html>
"""

MAIN_HTML = """
<!DOCTYPE html>
<html>
<head><title>initial</title></head>
<body style="margin: 0;">
	<div style="height: 250px;">tall header so top-viewport and frame-local coordinates diverge</div>
	<iframe id="test-iframe" src="/iframe-content" style="width: 600px; height: 400px; border: 0;"></iframe>
</body>
</html>
"""


@pytest.fixture
async def browser_session():
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
		)
	)
	await session.start()
	yield session
	await session.kill()


async def test_same_origin_iframe_click_fires_real_mouse_events(httpserver, browser_session: BrowserSession):
	"""Clicking a button inside a same-origin iframe must dispatch real mouse events."""
	httpserver.expect_request('/main').respond_with_data(MAIN_HTML, content_type='text/html')
	httpserver.expect_request('/iframe-content').respond_with_data(IFRAME_HTML, content_type='text/html')

	await browser_session.navigate_to(httpserver.url_for('/main'))
	await asyncio.sleep(1)

	browser_state = await browser_session.get_browser_state_summary(
		include_screenshot=False,
		include_recent_events=False,
	)
	selector_map = browser_state.dom_state.selector_map

	button_idx = None
	for idx, element in selector_map.items():
		if element.attributes and element.attributes.get('id') == 'iframe-button':
			button_idx = idx
			break
	assert button_idx is not None, f'iframe button not found in selector map ({len(selector_map)} elements)'

	tools = Tools()
	result = await tools.click(index=button_idx, browser_session=browser_session)
	assert result.error is None, f'click failed: {result.error}'

	await asyncio.sleep(0.5)
	cdp_session = await browser_session.get_or_create_cdp_session()
	eval_result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': 'document.title', 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	title = eval_result['result'].get('value')
	assert title == 'mousedown-received', (
		f'expected a real mouse click (mousedown) on the iframe button, got title={title!r} — '
		f"'click-only' means the click was downgraded to the JS this.click() fallback"
	)
