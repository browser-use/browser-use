import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.controller.service import Controller
from browser_use.controller.views import (
	GoToUrlAction,
	ScrollAction,
)


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server that serves static content."""
	server = HTTPServer()
	server.start()

	# Add routes for common test pages
	server.expect_request('/').respond_with_data(
		'<html><head><title>Test Home Page</title></head><body><h1>Test Home Page</h1><p>Welcome to the test site</p></body></html>',
		content_type='text/html',
	)

	server.expect_request('/scrollable').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head>
			<title>Scrollable Page</title>
			<style>
				body { margin: 0; padding: 20px; }
				.content { height: 3000px; background: linear-gradient(to bottom, #f0f0f0, #333); }
				.marker { padding: 20px; background: #007bff; color: white; margin: 500px 0; }
			</style>
		</head>
		<body>
			<h1>Scrollable Test Page</h1>
			<div class="content">
				<div class="marker" id="marker1">Marker 1</div>
				<div class="marker" id="marker2">Marker 2</div>
				<div class="marker" id="marker3">Marker 3</div>
			</div>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	"""Return the base URL for the test HTTP server."""
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
async def browser_session():
	"""Create and provide a Browser instance with security disabled."""
	profile = BrowserProfile(headless=True, disable_security=True, cross_origin_iframes=False)
	session = BrowserSession(browser_profile=profile)
	await session.start()
	yield session
	await session.kill()


@pytest.fixture
def controller():
	"""Create and provide a Controller instance."""
	return Controller()


class TestScrollActions:
	"""Test scroll-related actions and events."""

	async def test_scroll_actions(self, controller, browser_session, base_url, http_server):
		"""Test basic scroll action functionality."""

		# Navigate to scrollable page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/scrollable', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)

		# Test 1: Basic page scroll down
		scroll_action = {'scroll': ScrollAction(down=True, num_pages=1.0)}

		class ScrollActionModel(ActionModel):
			scroll: ScrollAction | None = None

		result = await controller.act(ScrollActionModel(**scroll_action), browser_session)

		# Verify scroll down succeeded
		assert isinstance(result, ActionResult)
		assert result.error is None, f'Scroll down failed: {result.error}'
		assert result.extracted_content is not None
		assert 'Scrolled down' in result.extracted_content
		assert 'the page' in result.extracted_content
		assert result.include_in_memory is True

		# Test 2: Basic page scroll up
		scroll_up_action = {'scroll': ScrollAction(down=False, num_pages=0.5)}
		result = await controller.act(ScrollActionModel(**scroll_up_action), browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is None, f'Scroll up failed: {result.error}'
		assert result.extracted_content is not None
		assert 'Scrolled up' in result.extracted_content
		assert '0.5 pages' in result.extracted_content

		# Test 3: Test with invalid element index (should error)
		invalid_scroll_action = {'scroll': ScrollAction(down=True, num_pages=1.0, frame_element_index=999)}
		result = await controller.act(ScrollActionModel(**invalid_scroll_action), browser_session)

		# This should fail with error about element not found
		assert isinstance(result, ActionResult)
		assert result.error is not None, 'Expected error for invalid element index'
		assert 'Element index 999 not found' in result.error or 'Failed to scroll' in result.error

		# Test 4: Model parameter validation
		scroll_with_index = ScrollAction(down=True, num_pages=1.0, frame_element_index=5)
		assert scroll_with_index.down is True
		assert scroll_with_index.num_pages == 1.0
		assert scroll_with_index.frame_element_index == 5

		scroll_without_index = ScrollAction(down=False, num_pages=0.25)
		assert scroll_without_index.down is False
		assert scroll_without_index.num_pages == 0.25
		assert scroll_without_index.frame_element_index is None

	async def test_scroll_with_cross_origin_disabled(self, browser_session, base_url):
		"""Test that scroll works when cross_origin_iframes is disabled."""
		from browser_use.browser.events import ScrollEvent

		# Navigate to a page
		await browser_session._cdp_navigate(f'{base_url}/scrollable')
		await asyncio.sleep(0.5)

		# Test simple scroll - should not hang
		event = browser_session.event_bus.dispatch(ScrollEvent(direction='down', amount=500))
		result = await asyncio.wait_for(event, timeout=3.0)
		assert result is not None

		# Test scroll up
		event = browser_session.event_bus.dispatch(ScrollEvent(direction='up', amount=200))
		result = await asyncio.wait_for(event, timeout=3.0)
		assert result is not None

	async def test_scroll_event_directly(self, browser_session):
		"""Test ScrollEvent directly through the event bus."""
		from browser_use.browser.events import ScrollEvent

		# Test scroll on about:blank (should work)
		event = browser_session.event_bus.dispatch(ScrollEvent(direction='down', amount=100))
		result = await asyncio.wait_for(event, timeout=2.0)
		event_result = await result.event_result()
		assert event_result is not None
		assert event_result.get('success') is True

	async def test_scroll_non_scrollable_page(self, browser_session, base_url, http_server):
		"""Test scrolling a page that's only 100px tall (not scrollable)."""
		from browser_use.browser.events import ScrollEvent

		# Add a non-scrollable page (content fits in viewport)
		http_server.expect_request('/non-scrollable').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Non-Scrollable Page</title>
				<style>
					body { margin: 0; padding: 10px; height: 80px; overflow: hidden; }
					.content { height: 60px; background: #f0f0f0; }
				</style>
			</head>
			<body>
				<div class="content">This page is too small to scroll</div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to non-scrollable page
		await browser_session._cdp_navigate(f'{base_url}/non-scrollable')
		await asyncio.sleep(0.5)

		# Get initial scroll position
		cdp_session = await browser_session.get_or_create_cdp_session()
		initial_scroll = await browser_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'window.pageYOffset', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		initial_y = initial_scroll.get('result', {}).get('value', 0)

		# Try to scroll down - should succeed but not actually move
		event = browser_session.event_bus.dispatch(ScrollEvent(direction='down', amount=500))
		result = await asyncio.wait_for(event, timeout=3.0)
		event_result = await result.event_result()
		assert event_result is not None
		assert event_result.get('success') is True

		# Check scroll position didn't change (page isn't scrollable)
		final_scroll = await browser_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'window.pageYOffset', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		final_y = final_scroll.get('result', {}).get('value', 0)
		assert final_y == initial_y, f'Scroll position changed on non-scrollable page: {initial_y} -> {final_y}'

	async def test_scroll_very_long_page(self, browser_session, base_url, http_server):
		"""Test scrolling a very long page (over 10,000px) by 8,000px."""
		from browser_use.browser.events import ScrollEvent

		# Add a very long page
		http_server.expect_request('/very-long').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Very Long Page</title>
				<style>
					body { margin: 0; padding: 20px; }
					.content { height: 12000px; background: linear-gradient(to bottom, #f0f0f0, #333); }
					.marker { padding: 20px; background: #007bff; color: white; margin: 2000px 0; }
				</style>
			</head>
			<body>
				<h1 id="top">Very Long Page - Top</h1>
				<div class="content">
					<div class="marker" id="marker1">Marker 1 at 2000px</div>
					<div class="marker" id="marker2">Marker 2 at 4000px</div>
					<div class="marker" id="marker3">Marker 3 at 6000px</div>
					<div class="marker" id="marker4">Marker 4 at 8000px</div>
					<div class="marker" id="marker5">Marker 5 at 10000px</div>
				</div>
				<h1 id="bottom">Very Long Page - Bottom</h1>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to very long page
		await browser_session._cdp_navigate(f'{base_url}/very-long')
		await asyncio.sleep(0.5)

		# Get initial scroll position
		cdp_session = await browser_session.get_or_create_cdp_session()
		initial_scroll = await browser_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'window.pageYOffset', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		initial_y = initial_scroll.get('result', {}).get('value', 0)
		assert initial_y == 0, f'Page should start at top, but pageYOffset is {initial_y}'

		# Scroll down by 8000px
		event = browser_session.event_bus.dispatch(ScrollEvent(direction='down', amount=8000))
		result = await asyncio.wait_for(event, timeout=3.0)
		event_result = await result.event_result()
		assert event_result is not None
		assert event_result.get('success') is True

		# Wait a bit for scroll to take effect
		await asyncio.sleep(0.5)

		# Check scroll position moved significantly
		final_scroll = await browser_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'window.pageYOffset', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		final_y = final_scroll.get('result', {}).get('value', 0)

		# Get page height to understand constraints
		page_height = await browser_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'document.body.scrollHeight', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		scroll_height = page_height.get('result', {}).get('value', 0)

		# Should have scrolled down significantly (might not be exactly 8000 due to viewport constraints)
		assert final_y > 5000, f'Expected to scroll significantly (page height: {scroll_height}px), but only at {final_y}px'

		# Verify we can see marker 4 which is at 8000px
		marker4_visible = await browser_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': """
					(() => {
						const marker = document.getElementById('marker4');
						const rect = marker.getBoundingClientRect();
						return rect.top >= 0 && rect.top <= window.innerHeight;
					})()
				""",
				'returnByValue': True,
			},
			session_id=cdp_session.session_id,
		)
		assert marker4_visible.get('result', {}).get('value', False), 'Marker 4 should be visible after scrolling 8000px'

	async def test_scroll_iframe_content(self, browser_session, base_url, http_server):
		"""Test scrolling inside a same-origin iframe."""
		from browser_use.browser.events import ScrollEvent

		# Add iframe content page
		http_server.expect_request('/iframe-content').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<style>
					body { margin: 0; padding: 10px; }
					.content { height: 2000px; background: linear-gradient(to bottom, #e0e0e0, #666); }
				</style>
			</head>
			<body>
				<h2 id="iframe-top">Iframe Content - Top</h2>
				<div class="content">
					<div style="margin-top: 900px;">Middle of iframe content</div>
					<div style="margin-top: 900px;">Bottom of iframe content</div>
				</div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Add main page with iframe
		http_server.expect_request('/page-with-iframe').respond_with_data(
			f"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Page with Iframe</title>
				<style>
					body {{ margin: 0; padding: 20px; }}
					#main-content {{ height: 200px; background: #f0f0f0; }}
					#scrollable-iframe {{ 
						width: 100%; 
						height: 400px; 
						border: 2px solid #333;
					}}
				</style>
			</head>
			<body>
				<div id="main-content">
					<h1>Main Page Content</h1>
					<p>This is the main page with an embedded iframe below.</p>
				</div>
				<iframe id="scrollable-iframe" src="{base_url}/iframe-content"></iframe>
				<div style="height: 200px; background: #e0e0e0;">
					<p>Content after iframe</p>
				</div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to page with iframe
		await browser_session._cdp_navigate(f'{base_url}/page-with-iframe')
		await asyncio.sleep(1.0)  # Give iframe time to load

		# Get initial scroll position of main page and iframe
		cdp_session = await browser_session.get_or_create_cdp_session()

		# Check main page scroll
		main_scroll = await browser_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'window.pageYOffset', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		main_y = main_scroll.get('result', {}).get('value', 0)

		# Check iframe scroll (should start at 0)
		iframe_initial = await browser_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': """
					(() => {
						const iframe = document.getElementById('scrollable-iframe');
						if (iframe && iframe.contentWindow) {
							return iframe.contentWindow.pageYOffset || 0;
						}
						return -1;
					})()
				""",
				'returnByValue': True,
			},
			session_id=cdp_session.session_id,
		)
		iframe_y = iframe_initial.get('result', {}).get('value', -1)
		assert iframe_y == 0, f'Iframe should start at top, but pageYOffset is {iframe_y}'

		# Scroll the main page first to bring iframe into view
		event = browser_session.event_bus.dispatch(ScrollEvent(direction='down', amount=100))
		await asyncio.wait_for(event, timeout=3.0)

		# Now try to scroll inside the iframe
		# Note: This would require finding the iframe element and scrolling it specifically
		# For now, we just verify the iframe exists and is scrollable
		iframe_scrollable = await browser_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': """
					(() => {
						const iframe = document.getElementById('scrollable-iframe');
						if (iframe && iframe.contentDocument) {
							const iframeBody = iframe.contentDocument.body;
							return iframeBody.scrollHeight > iframe.clientHeight;
						}
						return false;
					})()
				""",
				'returnByValue': True,
			},
			session_id=cdp_session.session_id,
		)
		assert iframe_scrollable.get('result', {}).get('value', False), 'Iframe should be scrollable'
