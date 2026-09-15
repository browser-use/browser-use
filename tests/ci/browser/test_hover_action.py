"""Tests for the hover action (CSS :hover / JS mouseenter reveal)."""

import pytest

from browser_use.browser.profile import BrowserProfile, ViewportSize
from browser_use.browser.session import BrowserSession
from browser_use.tools.service import Tools
from browser_use.tools.views import HoverElementAction


@pytest.fixture
async def browser_session():
	"""Create a simple headless browser session for hover tests."""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			window_size=ViewportSize(width=1280, height=1000),
		)
	)
	await session.start()
	yield session
	await session.kill()


HOVER_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head>
<style>
	.menu { position: relative; display: inline-block; }
	.dropdown {
		display: none;
		position: absolute;
		border: 1px solid black;
	}
	.menu:hover .dropdown { display: block; }
</style>
</head>
<body>
	<div class="menu" id="menu-trigger" tabindex="0">
		Products
		<div class="dropdown" id="dropdown-content">
			<a href="/a">Item A</a>
			<a href="/b">Item B</a>
		</div>
	</div>
	<script>
		document.getElementById('menu-trigger').addEventListener('mouseenter', function () {
			window.__hoverFired = true;
		});
	</script>
</body>
</html>
"""


class TestHoverAction:
	"""Verify the `hover` tool triggers CSS :hover state and JS mouseenter listeners."""

	async def test_hover_reveals_css_dropdown(self, httpserver, browser_session: BrowserSession):
		"""Hovering the trigger should make the CSS-only dropdown visible."""
		httpserver.expect_request('/hover-test').respond_with_data(HOVER_PAGE_HTML, content_type='text/html')
		url = httpserver.url_for('/hover-test')

		await browser_session.navigate_to(url)

		browser_state = await browser_session.get_browser_state_summary(include_screenshot=False)
		assert browser_state.dom_state is not None

		# Find the hover trigger by its element id in the selector map
		trigger_index = None
		for idx, element in browser_state.dom_state.selector_map.items():
			if element.attributes and element.attributes.get('id') == 'menu-trigger':
				trigger_index = idx
				break

		assert trigger_index is not None, 'Could not find #menu-trigger element in selector map'

		tools = Tools()
		hover_action = tools.registry.registry.actions['hover']
		result = await hover_action.function(
			params=HoverElementAction(index=trigger_index),
			browser_session=browser_session,
		)

		assert result.error is None, f'Hover action failed: {result.error}'

		# Verify the JS mouseenter listener fired
		cdp_session = await browser_session.get_or_create_cdp_session()
		eval_result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'window.__hoverFired === true'},
			session_id=cdp_session.session_id,
		)
		assert eval_result.get('result', {}).get('value') is True, 'mouseenter listener did not fire on hover'

		# Verify the CSS-revealed dropdown is now visible (display != none)
		eval_display = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "getComputedStyle(document.getElementById('dropdown-content')).display"},
			session_id=cdp_session.session_id,
		)
		assert eval_display.get('result', {}).get('value') != 'none', 'CSS :hover dropdown did not become visible'

	async def test_hover_invalid_index_returns_helpful_message(self, httpserver, browser_session: BrowserSession):
		"""Hovering a stale/invalid index should return a clear message, not raise."""
		httpserver.expect_request('/hover-empty').respond_with_data(
			'<html><body><p>no interactive elements</p></body></html>', content_type='text/html'
		)
		url = httpserver.url_for('/hover-empty')
		await browser_session.navigate_to(url)
		await browser_session.get_browser_state_summary(include_screenshot=False)

		tools = Tools()
		hover_action = tools.registry.registry.actions['hover']
		result = await hover_action.function(
			params=HoverElementAction(index=999),
			browser_session=browser_session,
		)

		assert result.error is None
		assert 'not available' in (result.extracted_content or '')
