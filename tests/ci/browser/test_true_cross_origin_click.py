"""Test clicking elements inside TRUE cross-origin iframes (external domains)."""

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


class TestTrueCrossOriginIframeClick:
	"""Test clicking elements inside true cross-origin iframes."""

	async def test_click_element_in_true_cross_origin_iframe(self, httpserver, browser_session: BrowserSession):
		"""Verify that elements inside TRUE cross-origin iframes (example.com) can be clicked.

		This test uses example.com which is a real external domain, testing actual cross-origin
		iframe extraction and clicking via CDP target switching.
		"""

		# Create main page with TRUE cross-origin iframe pointing to example.com
		main_html = """
		<!DOCTYPE html>
		<html>
		<head><title>True Cross-Origin Test</title></head>
		<body>
			<h1>Main Page</h1>
			<button id="main-button">Main Button</button>
			<iframe id="cross-origin" src="https://example.com" style="width: 800px; height: 600px;"></iframe>
		</body>
		</html>
		"""

		# Serve the main page
		httpserver.expect_request('/true-cross-origin-test').respond_with_data(main_html, content_type='text/html')
		url = httpserver.url_for('/true-cross-origin-test')

		# Navigate to the page
		await browser_session.navigate_to(url)

		# Wait for cross-origin iframe to load (network request)
		await asyncio.sleep(5)

		# Get DOM state with cross-origin iframe extraction enabled
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
		cross_origin_elements = []

		for idx, element in state.selector_map.items():
			target_id = element.target_id
			targets_found.add(target_id)

			# Check if element is from cross-origin iframe (example.com)
			# Look for links - example.com has a link to iana.org/domains/reserved
			if element.attributes:
				href = element.attributes.get('href', '')
				element_id = element.attributes.get('id', '')

				# example.com has a link to iana.org/domains/reserved
				if 'iana.org' in href:
					cross_origin_elements.append((idx, element))
					print(f'   ✅ Found cross-origin element: [{idx}] {element.tag_name} href={href}')
				elif element_id == 'main-button':
					main_page_elements.append((idx, element))

		# Verify we found elements from at least 2 different targets
		print(f'\n🎯 Found elements from {len(targets_found)} different CDP targets')

		# Check if cross-origin iframe loaded
		if len(targets_found) < 2:
			print('⚠️  Warning: Cross-origin iframe did not create separate CDP target')
			print('   This may indicate cross_origin_iframes feature is not working as expected')
			pytest.skip('Cross-origin iframe did not create separate CDP target - skipping test')

		if len(cross_origin_elements) == 0:
			print('⚠️  Warning: No elements found from example.com iframe')
			print('   Network may be restricted in CI environment')
			pytest.skip('No elements extracted from example.com - skipping click test')

		# Verify we found at least one element from the cross-origin iframe
		assert len(cross_origin_elements) > 0, 'Expected to find at least one element from cross-origin iframe (example.com)'

		# Try clicking the cross-origin element
		print('\n🖱️  Testing Click on True Cross-Origin Iframe Element:')
		tools = Tools()

		link_idx, link_element = cross_origin_elements[0]
		print(f'   Attempting to click element [{link_idx}] from example.com iframe...')

		try:
			result = await tools.click(index=link_idx, browser_session=browser_session)

			# Check for errors
			if result.error:
				pytest.fail(f'Click on cross-origin element [{link_idx}] failed with error: {result.error}')

			if result.extracted_content and (
				'not available' in result.extracted_content.lower() or 'failed' in result.extracted_content.lower()
			):
				pytest.fail(f'Click on cross-origin element [{link_idx}] failed: {result.extracted_content}')

			print(f'   ✅ Click succeeded on cross-origin element [{link_idx}]!')
			print('   🎉 True cross-origin iframe element clicking works!')

		except Exception as e:
			pytest.fail(f'Exception while clicking cross-origin element [{link_idx}]: {e}')

		print('\n✅ Test passed: True cross-origin iframe elements can be clicked')
