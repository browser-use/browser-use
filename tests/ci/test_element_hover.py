"""Tests for hovering elements through the Actor API."""

from browser_use.browser.session import BrowserSession


async def test_hover_targets_visible_part_of_element(httpserver, browser_session: BrowserSession):
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
						height: 250vh;
					}
				</style>
			</head>
			<body>
				<div
					id="target"
					onmousemove="
						this.dataset.hovered = 'true';
						this.dataset.hoverY = event.clientY;
						this.dataset.viewportHeight = window.innerHeight;
					"
				></div>
			</body>
		</html>
		""",
		content_type='text/html',
	)

	await browser_session.navigate_to(httpserver.url_for('/large-hover-target'))
	page = await browser_session.must_get_current_page()
	targets = await page.get_elements_by_css_selector('#target')

	assert len(targets) == 1
	await targets[0].hover()
	assert await targets[0].get_attribute('data-hovered') == 'true'
	hover_y = int(await targets[0].get_attribute('data-hover-y') or '-1')
	viewport_height = int(await targets[0].get_attribute('data-viewport-height') or '-1')
	assert 0 <= hover_y < viewport_height
