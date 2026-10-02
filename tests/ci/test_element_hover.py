"""Tests for hovering elements through the Actor API."""

import pytest

from browser_use.browser.session import BrowserSession


async def test_hover_targets_visible_visual_viewport_and_rejects_offscreen_elements(httpserver, browser_session: BrowserSession):
	httpserver.expect_request('/large-hover-target').respond_with_data(
		"""
		<!doctype html>
		<html>
			<head>
				<style>
					html, body { margin: 0; }
					#target {
						position: fixed;
						top: -200vh;
						width: 100vw;
						height: 300vh;
					}
					#offscreen {
						position: fixed;
						top: -400vh;
						width: 100vw;
						height: 100vh;
					}
				</style>
			</head>
			<body>
				<div
					id="target"
					onmousemove="
						this.dataset.hovered = 'true';
						this.dataset.hoverY = event.clientY;
						this.dataset.viewportTop = window.visualViewport.offsetTop;
						this.dataset.viewportHeight = window.visualViewport.height;
					"
				></div>
				<div id="offscreen"></div>
			</body>
		</html>
		""",
		content_type='text/html',
	)

	await browser_session.navigate_to(httpserver.url_for('/large-hover-target'))
	page = await browser_session.must_get_current_page()
	targets = await page.get_elements_by_css_selector('#target')
	offscreen_targets = await page.get_elements_by_css_selector('#offscreen')
	session_id = await page.session_id

	assert len(targets) == 1
	assert len(offscreen_targets) == 1
	await browser_session.cdp_client.send.Emulation.setPageScaleFactor(
		params={'pageScaleFactor': 2},
		session_id=session_id,
	)
	try:
		await targets[0].hover()
		assert await targets[0].get_attribute('data-hovered') == 'true'
		hover_y = float(await targets[0].get_attribute('data-hover-y') or '-1')
		viewport_top = float(await targets[0].get_attribute('data-viewport-top') or '-1')
		viewport_height = float(await targets[0].get_attribute('data-viewport-height') or '-1')
		assert abs(hover_y - (viewport_top + viewport_height / 2)) <= 1

		with pytest.raises(RuntimeError, match='Element is outside the viewport'):
			await offscreen_targets[0].hover()
	finally:
		await browser_session.cdp_client.send.Emulation.setPageScaleFactor(
			params={'pageScaleFactor': 1},
			session_id=session_id,
		)
