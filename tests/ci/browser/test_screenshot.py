import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.service import Agent
from browser_use.browser.events import NavigateToUrlEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from tests.ci.conftest import create_mock_llm


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server for screenshot tests."""
	server = HTTPServer()
	server.start()

	# Route: Page with visible content for screenshot testing
	server.expect_request('/screenshot-page').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head>
			<title>Screenshot Test Page</title>
			<style>
				body { font-family: Arial; padding: 20px; background: #f0f0f0; }
				h1 { color: #333; font-size: 32px; }
				.content { background: white; padding: 20px; border-radius: 8px; margin: 10px 0; }
			</style>
		</head>
		<body>
			<h1>Screenshot Test Page</h1>
			<div class="content">
				<p>This page is used to test screenshot capture with vision enabled.</p>
				<p>The agent should capture a screenshot when navigating to this page.</p>
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


@pytest.fixture(scope='function')
async def browser_session():
	session = BrowserSession(browser_profile=BrowserProfile(headless=True))
	await session.start()
	yield session
	await session.kill()


@pytest.mark.asyncio
async def test_basic_screenshots(browser_session: BrowserSession, httpserver):
	"""Navigate to a local page and ensure screenshot helpers return bytes."""

	html = """
    <html><body><h1 id='title'>Hello</h1><p>Screenshot demo.</p></body></html>
    """
	httpserver.expect_request('/demo').respond_with_data(html, content_type='text/html')
	url = httpserver.url_for('/demo')

	nav = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=url, new_tab=False))
	await nav

	data = await browser_session.take_screenshot(full_page=False)
	assert data, 'Viewport screenshot returned no data'

	element = await browser_session.screenshot_element('h1')
	assert element, 'Element screenshot returned no data'


async def test_element_screenshots_capture_the_element_after_scrolling(browser_session: BrowserSession, httpserver):
	"""Element screenshots must capture the element itself once the page is scrolled past it."""
	import base64
	import io

	from PIL import Image

	html = """
	<html><body style="margin: 0">
		<div style="height: 3000px; background: rgb(0, 0, 255)"></div>
		<div id="target" style="width: 200px; height: 100px; background: rgb(255, 0, 0)"></div>
		<div style="height: 3000px; background: rgb(0, 255, 0)"></div>
	</body></html>
	"""
	httpserver.expect_request('/scrolled').respond_with_data(html, content_type='text/html')
	await browser_session.event_bus.dispatch(NavigateToUrlEvent(url=httpserver.url_for('/scrolled'), new_tab=False))

	page = await browser_session.get_current_page()
	assert page is not None
	element = (await page.get_elements_by_css_selector('#target'))[0]
	await element.scroll_into_view()
	assert float(await page.evaluate('() => window.scrollY')) > 0

	def center_pixel(data: bytes) -> tuple[int, ...]:
		with Image.open(io.BytesIO(data)) as image:
			rgb = image.convert('RGB')
			return rgb.getpixel((rgb.width // 2, rgb.height // 2))  # type: ignore[return-value]

	assert center_pixel(base64.b64decode(await element.screenshot())) == (255, 0, 0)
	assert center_pixel(await browser_session.screenshot_element('#target')) == (255, 0, 0)


async def test_agent_screenshot_with_vision_enabled(browser_session, base_url):
	"""Test that agent captures screenshots when vision is enabled.

	This integration test verifies that:
	1. Agent with vision=True navigates to a page
	2. After prepare_context/update message manager, screenshot is captured
	3. Screenshot is included in the agent's history state
	"""

	# Create mock LLM actions
	actions = [
		f"""
		{{
			"thinking": "I'll navigate to the screenshot test page",
			"evaluation_previous_goal": "Starting task",
			"memory": "Navigating to page",
			"next_goal": "Navigate to test page",
			"action": [
				{{
					"navigate": {{
						"url": "{base_url}/screenshot-page",
						"new_tab": false
					}}
				}}
			]
		}}
		""",
		"""
		{
			"thinking": "Page loaded, completing task",
			"evaluation_previous_goal": "Page loaded",
			"memory": "Task completed",
			"next_goal": "Complete task",
			"action": [
				{
					"done": {
						"text": "Successfully navigated and captured screenshot",
						"success": true
					}
				}
			]
		}
		""",
	]

	mock_llm = create_mock_llm(actions=actions)

	# Create agent with vision enabled
	agent = Agent(
		task=f'Navigate to {base_url}/screenshot-page',
		llm=mock_llm,
		browser_session=browser_session,
		use_vision=True,  # Enable vision/screenshots
	)

	# Run agent
	history = await agent.run(max_steps=2)

	# Verify agent completed successfully
	assert len(history) >= 1, 'Agent should have completed at least 1 step'
	final_result = history.final_result()
	assert final_result is not None, 'Agent should return a final result'

	# Verify screenshots were captured in the history
	screenshot_found = False
	for i, step in enumerate(history.history):
		# Check if browser state has screenshot path
		if step.state and hasattr(step.state, 'screenshot_path') and step.state.screenshot_path:
			screenshot_found = True
			print(f'\n✅ Step {i + 1}: Screenshot captured at {step.state.screenshot_path}')

			# Verify screenshot file exists (it should be saved to disk)
			import os

			assert os.path.exists(step.state.screenshot_path), f'Screenshot file should exist at {step.state.screenshot_path}'

			# Verify screenshot file has content
			screenshot_size = os.path.getsize(step.state.screenshot_path)
			assert screenshot_size > 0, f'Screenshot file should have content, got {screenshot_size} bytes'
			print(f'   Screenshot size: {screenshot_size} bytes')

	assert screenshot_found, 'At least one screenshot should be captured when vision is enabled'

	print('\n🎉 Integration test passed: Screenshots are captured correctly with vision enabled')
