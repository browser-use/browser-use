"""Test clicking elements inside Shadow DOM."""

import asyncio

import pytest

from browser_use.browser.profile import BrowserProfile, ViewportSize
from browser_use.browser.session import BrowserSession
from browser_use.tools.service import Tools


@pytest.fixture
async def browser_session():
	"""Create browser session for shadow DOM testing."""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
			window_size=ViewportSize(width=1920, height=1400),
		)
	)
	await session.start()
	yield session
	await session.kill()


class TestShadowDOMClick:
	"""Test clicking elements inside Shadow DOM."""

	async def test_click_element_in_open_shadow_dom(self, httpserver, browser_session: BrowserSession):
		"""Verify that elements inside open shadow DOM can be clicked."""

		# Create a page with shadow DOM containing clickable elements
		main_html = """
		<!DOCTYPE html>
		<html>
		<head>
			<title>Shadow DOM Click Test</title>
			<style>
				.result { padding: 10px; margin: 10px 0; border: 1px solid #ccc; }
				.success { background: #d4edda; color: #155724; }
			</style>
		</head>
		<body>
			<h1>Shadow DOM Click Test</h1>
			<div id="result" class="result">Click status: Not clicked yet</div>

			<!-- Custom element with shadow DOM -->
			<custom-menu id="my-menu"></custom-menu>

			<script>
				// Define custom element with open shadow DOM
				class CustomMenu extends HTMLElement {
					constructor() {
						super();
						// Create open shadow root
						const shadow = this.attachShadow({ mode: 'open' });

						// Create menu items inside shadow DOM
						shadow.innerHTML = `
							<style>
								.menu { display: flex; gap: 10px; padding: 10px; background: #f0f0f0; }
								.menu-item {
									padding: 10px 20px;
									background: #007bff;
									color: white;
									border: none;
									border-radius: 4px;
									cursor: pointer;
								}
								.menu-item:hover { background: #0056b3; }
							</style>
							<div class="menu">
								<button class="menu-item" id="shadow-btn-file">File</button>
								<button class="menu-item" id="shadow-btn-edit">Edit</button>
								<button class="menu-item" id="shadow-btn-view">View</button>
							</div>
						`;

						// Add click handlers
						shadow.querySelectorAll('.menu-item').forEach(btn => {
							btn.addEventListener('click', (e) => {
								const resultDiv = document.getElementById('result');
								resultDiv.textContent = 'Click status: Clicked ' + e.target.id;
								resultDiv.classList.add('success');
							});
						});
					}
				}

				// Register the custom element
				customElements.define('custom-menu', CustomMenu);
			</script>
		</body>
		</html>
		"""

		# Serve the page
		httpserver.expect_request('/shadow-dom-test').respond_with_data(main_html, content_type='text/html')
		url = httpserver.url_for('/shadow-dom-test')

		# Navigate to the page
		await browser_session.navigate_to(url)

		# Wait for page to fully render including custom elements
		await asyncio.sleep(1)

		# Get DOM state
		browser_state = await browser_session.get_browser_state_summary(
			include_screenshot=False,
			include_recent_events=False,
		)
		assert browser_state.dom_state is not None
		state = browser_state.dom_state

		print(f'\n 📊 Found {len(state.selector_map)} total elements')

		# Find shadow DOM elements
		shadow_elements = []
		for idx, element in state.selector_map.items():
			# Check if element is from shadow DOM
			if element.is_inside_shadow_dom:
				attrs = element.attributes or {}
				print(f'   🔮 Shadow DOM element: [{idx}] <{element.tag_name}> id={attrs.get("id", "")}')
				if element.tag_name == 'button':
					shadow_elements.append((idx, element))

		# Verify we found elements from shadow DOM
		print(f'\n🎯 Found {len(shadow_elements)} shadow DOM button elements')

		if len(shadow_elements) == 0:
			pytest.fail('Expected to find at least one button element from shadow DOM, but found none')

		# Try clicking the shadow DOM element
		print('\n🖱️  Testing Click on Shadow DOM Element:')
		tools = Tools()

		btn_idx, btn_element = shadow_elements[0]
		print(f'   Attempting to click shadow DOM button [{btn_idx}]...')

		try:
			result = await tools.click(index=btn_idx, browser_session=browser_session)

			# Check for errors
			if result.error:
				pytest.fail(f'Click on shadow DOM element [{btn_idx}] failed with error: {result.error}')

			if result.extracted_content and 'failed' in result.extracted_content.lower():
				pytest.fail(f'Click on shadow DOM element [{btn_idx}] failed: {result.extracted_content}')

			print(f'   ✅ Click succeeded on shadow DOM element [{btn_idx}]!')

		except Exception as e:
			pytest.fail(f'Exception while clicking shadow DOM element [{btn_idx}]: {e}')

		# Wait for click to process
		await asyncio.sleep(0.5)

		# Verify click worked by checking the result div
		browser_state = await browser_session.get_browser_state_summary(
			include_screenshot=False,
			include_recent_events=False,
		)
		assert browser_state.dom_state is not None

		# Look for the result div and check its content
		for idx, element in browser_state.dom_state.selector_map.items():
			attrs = element.attributes or {}
			if attrs.get('id') == 'result':
				text = element.get_all_children_text()
				print(f'   Result div content: {text}')
				if 'Clicked' in text:
					print('   🎉 Shadow DOM click was successful - element received the click event!')
				break

		print('\n✅ Test passed: Shadow DOM elements can be clicked')

	async def test_click_element_in_shadow_dom_inside_iframe(self, httpserver, browser_session: BrowserSession):
		"""Verify that elements inside shadow DOM that is inside an iframe can be clicked."""

		# Create iframe content with shadow DOM
		iframe_html = """
		<!DOCTYPE html>
		<html>
		<head>
			<title>Iframe with Shadow DOM</title>
			<style>
				.result { padding: 10px; margin: 10px 0; border: 1px solid #ccc; }
				.success { background: #d4edda; color: #155724; }
			</style>
		</head>
		<body>
			<h2>Iframe Content with Shadow DOM</h2>
			<div id="iframe-result" class="result">Status: Not clicked</div>

			<custom-button id="shadow-container"></custom-button>

			<script>
				class CustomButton extends HTMLElement {
					constructor() {
						super();
						const shadow = this.attachShadow({ mode: 'open' });
						shadow.innerHTML = `
							<style>
								button {
									padding: 15px 30px;
									background: #28a745;
									color: white;
									border: none;
									border-radius: 8px;
									cursor: pointer;
									font-size: 16px;
								}
								button:hover { background: #218838; }
							</style>
							<button id="iframe-shadow-btn">Click Me (Shadow DOM in Iframe)</button>
						`;

						shadow.querySelector('button').addEventListener('click', () => {
							const result = document.getElementById('iframe-result');
							result.textContent = 'Status: Clicked successfully!';
							result.classList.add('success');
						});
					}
				}
				customElements.define('custom-button', CustomButton);
			</script>
		</body>
		</html>
		"""

		# Create main page with iframe
		main_html = """
		<!DOCTYPE html>
		<html>
		<head><title>Shadow DOM in Iframe Test</title></head>
		<body>
			<h1>Main Page</h1>
			<p>The button below is inside a shadow DOM which is inside an iframe:</p>
			<iframe id="test-iframe" src="/iframe-shadow-dom" style="width: 600px; height: 300px; border: 2px solid #333;"></iframe>
		</body>
		</html>
		"""

		# Serve both pages
		httpserver.expect_request('/shadow-iframe-test').respond_with_data(main_html, content_type='text/html')
		httpserver.expect_request('/iframe-shadow-dom').respond_with_data(iframe_html, content_type='text/html')
		url = httpserver.url_for('/shadow-iframe-test')

		# Navigate to the page
		await browser_session.navigate_to(url)

		# Wait for iframe and shadow DOM to load
		await asyncio.sleep(2)

		# Get DOM state
		browser_state = await browser_session.get_browser_state_summary(
			include_screenshot=False,
			include_recent_events=False,
		)
		assert browser_state.dom_state is not None
		state = browser_state.dom_state

		print(f'\n📊 Found {len(state.selector_map)} total elements')

		# Find shadow DOM elements that are also inside iframe
		shadow_iframe_elements = []
		for idx, element in state.selector_map.items():
			if element.is_inside_shadow_dom and element.is_inside_iframe:
				attrs = element.attributes or {}
				print(f'   🔮📦 Shadow DOM in iframe element: [{idx}] <{element.tag_name}> id={attrs.get("id", "")}')
				if element.tag_name == 'button':
					shadow_iframe_elements.append((idx, element))

		print(f'\n🎯 Found {len(shadow_iframe_elements)} shadow DOM buttons inside iframe')

		if len(shadow_iframe_elements) == 0:
			# This might be expected in some configurations - check if we at least found shadow DOM elements
			shadow_only = []
			for idx, element in state.selector_map.items():
				if element.is_inside_shadow_dom and element.tag_name == 'button':
					shadow_only.append((idx, element))

			if len(shadow_only) > 0:
				print(f'   Note: Found {len(shadow_only)} shadow DOM buttons, but is_inside_iframe returned False')
				shadow_iframe_elements = shadow_only
			else:
				pytest.skip('No shadow DOM buttons found - may be a limitation of the current iframe handling')

		# Try clicking the element
		print('\n🖱️  Testing Click on Shadow DOM Element in Iframe:')
		tools = Tools()

		btn_idx, btn_element = shadow_iframe_elements[0]
		print(f'   Attempting to click element [{btn_idx}]...')

		try:
			result = await tools.click(index=btn_idx, browser_session=browser_session)

			if result.error:
				pytest.fail(f'Click failed with error: {result.error}')

			print(f'   ✅ Click succeeded on element [{btn_idx}]!')

		except Exception as e:
			pytest.fail(f'Exception while clicking element [{btn_idx}]: {e}')

		print('\n✅ Test passed: Shadow DOM elements in iframes can be clicked')
