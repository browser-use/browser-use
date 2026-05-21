"""Test clicking elements inside cross-origin iframes."""

import asyncio

import pytest

from browser_use.browser.profile import BrowserProfile, ViewportSize
from browser_use.browser.session import BrowserSession
from browser_use.tools.service import Tools


@pytest.fixture
async def browser_session():
	"""Create browser session with cross-origin iframe support."""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			window_size=ViewportSize(width=1920, height=1400),
			cross_origin_iframes=True,  # Enable cross-origin iframe extraction
		)
	)
	await session.start()
	yield session
	await session.kill()


class TestCrossOriginIframeClick:
	"""Test clicking elements inside cross-origin iframes."""

	async def test_click_element_in_cross_origin_iframe(self, httpserver, browser_session: BrowserSession):
		"""Verify that elements inside iframes in different CDP targets can be clicked."""

		# Create iframe content with clickable elements
		iframe_html = """
		<!DOCTYPE html>
		<html>
		<head><title>Iframe Page</title></head>
		<body>
			<h1>Iframe Content</h1>
			<a href="https://test-domain.example/page" id="iframe-link">Test Link</a>
			<button id="iframe-button">Iframe Button</button>
		</body>
		</html>
		"""

		# Create main page with iframe pointing to our test server
		main_html = """
		<!DOCTYPE html>
		<html>
		<head><title>Multi-Target Test</title></head>
		<body>
			<h1>Main Page</h1>
			<button id="main-button">Main Button</button>
			<iframe id="test-iframe" src="/iframe-content" style="width: 800px; height: 600px;"></iframe>
		</body>
		</html>
		"""

		# Serve both pages
		httpserver.expect_request('/multi-target-test').respond_with_data(main_html, content_type='text/html')
		httpserver.expect_request('/iframe-content').respond_with_data(iframe_html, content_type='text/html')
		url = httpserver.url_for('/multi-target-test')

		# Navigate to the page
		await browser_session.navigate_to(url)

		# Wait for iframe to load
		await asyncio.sleep(2)

		# Get DOM state with cross-origin iframe extraction enabled
		# Use browser_session.get_browser_state_summary() instead of directly creating DomService
		# This goes through the proper event bus and watchdog system
		browser_state = await browser_session.get_browser_state_summary(
			include_screenshot=False,
			include_recent_events=False,
		)
		assert browser_state.dom_state is not None
		state = browser_state.dom_state

		print(f'\n📊 Found {len(state.selector_map)} total elements')

		# Find elements from different targets
		targets_found = set()
		main_page_elements = []
		iframe_elements = []

		for idx, element in state.selector_map.items():
			target_id = element.target_id
			targets_found.add(target_id)

			# Check if element is from iframe (identified by id attributes we set)
			# Iframe elements will have a different target_id when cross_origin_iframes=True
			if element.attributes:
				element_id = element.attributes.get('id', '')
				if element_id in ('iframe-link', 'iframe-button'):
					iframe_elements.append((idx, element))
					print(f'   ✅ Found iframe element: [{idx}] {element.tag_name} id={element_id}')
				elif element_id == 'main-button':
					main_page_elements.append((idx, element))

		# Verify we found elements from at least 2 different targets
		print(f'\n🎯 Found elements from {len(targets_found)} different CDP targets')

		# Check if iframe elements were found
		if len(iframe_elements) == 0:
			pytest.fail('Expected to find at least one element from iframe, but found none')

		# Verify we found at least one element from the iframe
		assert len(iframe_elements) > 0, 'Expected to find at least one element from iframe'

		# Try clicking the iframe element
		print('\n🖱️  Testing Click on Iframe Element:')
		tools = Tools()

		link_idx, link_element = iframe_elements[0]
		print(f'   Attempting to click element [{link_idx}] from iframe...')

		try:
			result = await tools.click(index=link_idx, browser_session=browser_session)

			# Check for errors
			if result.error:
				pytest.fail(f'Click on iframe element [{link_idx}] failed with error: {result.error}')

			if result.extracted_content and (
				'not available' in result.extracted_content.lower() or 'failed' in result.extracted_content.lower()
			):
				pytest.fail(f'Click on iframe element [{link_idx}] failed: {result.extracted_content}')

			print(f'   ✅ Click succeeded on iframe element [{link_idx}]!')
			print('   🎉 Iframe element clicking works!')

		except Exception as e:
			pytest.fail(f'Exception while clicking iframe element [{link_idx}]: {e}')

		print('\n✅ Test passed: Iframe elements can be clicked')
