"""Regression coverage for preserving mouse position across button events."""

import json

from browser_use.browser.session import BrowserSession


async def _open_mouse_page(httpserver, browser_session: BrowserSession, path: str):
	httpserver.expect_request(path).respond_with_data(
		"""
		<html>
			<body style="margin: 0; width: 600px; height: 400px">
				<script>
					window.mouseEvents = [];
					for (const type of ['mousedown', 'mouseup']) {
						document.addEventListener(type, event => {
							window.mouseEvents.push({type, x: event.clientX, y: event.clientY});
						});
					}
				</script>
			</body>
		</html>
		""",
		content_type='text/html',
	)
	await browser_session.navigate_to(httpserver.url_for(path))
	page = await browser_session.get_current_page()
	assert page is not None
	return page, await page.mouse


async def test_drag_button_events_use_latest_mouse_position(httpserver, browser_session: BrowserSession):
	page, mouse = await _open_mouse_page(httpserver, browser_session, '/mouse-position')

	await mouse.move(120, 100)
	await mouse.down()
	await mouse.move(300, 200)
	await mouse.up()

	events = json.loads(await page.evaluate('() => window.mouseEvents'))
	assert events == [
		{'type': 'mousedown', 'x': 120, 'y': 100},
		{'type': 'mouseup', 'x': 300, 'y': 200},
	]


async def test_button_events_default_to_origin_before_mouse_moves(httpserver, browser_session: BrowserSession):
	page, mouse = await _open_mouse_page(httpserver, browser_session, '/mouse-origin')

	await mouse.down()
	await mouse.up()

	events = json.loads(await page.evaluate('() => window.mouseEvents'))
	assert events == [
		{'type': 'mousedown', 'x': 0, 'y': 0},
		{'type': 'mouseup', 'x': 0, 'y': 0},
	]
