"""Test DomService behavior with chrome:// URLs and new tab pages."""

import pytest

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.dom.service import DomService


class TestDomServiceChromeURLs:
	"""Test that DomService returns empty DOM for chrome:// URLs and new tabs."""

	@pytest.fixture
	async def browser_session(self):
		"""Create a browser session for testing."""
		profile = BrowserProfile(headless=True, user_data_dir=None, keep_alive=False)
		session = BrowserSession(browser_profile=profile)
		await session.start()
		yield session
		await session.kill()

	async def test_about_blank_returns_empty_dom(self, browser_session):
		"""Test that about:blank returns an empty DOM."""
		page = await browser_session.get_current_page()
		await page.goto('about:blank')

		dom_service = DomService(page)
		dom_state = await dom_service.get_clickable_elements()

		# Verify empty DOM is returned
		assert dom_state.element_tree.tag_name == 'body'
		assert dom_state.element_tree.xpath == ''
		assert dom_state.element_tree.attributes == {}
		assert dom_state.element_tree.children == []
		assert dom_state.element_tree.is_visible is False
		assert dom_state.selector_map == {}

	async def test_chrome_new_tab_page_returns_empty_dom(self, browser_session):
		"""Test that chrome://new-tab-page returns an empty DOM."""
		page = await browser_session.get_current_page()
		await page.goto('chrome://new-tab-page')

		dom_service = DomService(page)
		dom_state = await dom_service.get_clickable_elements()

		# Verify empty DOM
		assert dom_state.element_tree.tag_name == 'body'
		assert len(dom_state.element_tree.children) == 0
		assert dom_state.selector_map == {}

	async def test_chrome_version_returns_empty_dom(self, browser_session):
		"""Test that chrome://version returns an empty DOM."""
		page = await browser_session.get_current_page()
		await page.goto('chrome://version')

		dom_service = DomService(page)
		dom_state = await dom_service.get_clickable_elements()

		# Verify empty DOM
		assert dom_state.element_tree.tag_name == 'body'
		assert len(dom_state.element_tree.children) == 0
		assert dom_state.selector_map == {}

	async def test_regular_url_returns_populated_dom(self, browser_session, httpserver):
		"""Test that regular URLs still return a populated DOM."""
		# Set up test HTML
		httpserver.expect_request('/').respond_with_data("""
			<html>
				<body>
					<h1>Test Page</h1>
					<button id="test-button">Click me</button>
					<a href="#link">Test Link</a>
				</body>
			</html>
		""")

		page = await browser_session.get_current_page()
		await page.goto(httpserver.url_for('/'))

		dom_service = DomService(page)
		dom_state = await dom_service.get_clickable_elements()

		# Verify DOM is populated (either root is not body, or body has children)
		has_content = dom_state.element_tree.tag_name != 'body' or len(dom_state.element_tree.children) > 0
		assert has_content, f'Expected populated DOM but got empty tree with tag {dom_state.element_tree.tag_name}'
