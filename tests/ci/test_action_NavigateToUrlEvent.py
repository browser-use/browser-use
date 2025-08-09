import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.controller.service import Controller
from browser_use.controller.views import GoToUrlAction


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

	server.expect_request('/page1').respond_with_data(
		'<html><head><title>Test Page 1</title></head><body><h1>Test Page 1</h1><p>This is test page 1</p></body></html>',
		content_type='text/html',
	)

	server.expect_request('/page2').respond_with_data(
		'<html><head><title>Test Page 2</title></head><body><h1>Test Page 2</h1><p>This is test page 2</p></body></html>',
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


class TestNavigateToUrlEvent:
	"""Test NavigateToUrlEvent and go_to_url action functionality."""

	async def test_go_to_url_action(self, controller, browser_session: BrowserSession, base_url):
		"""Test that GoToUrlAction navigates to the specified URL and test both state summary methods."""
		# Test successful navigation to a valid page
		action_data = {'go_to_url': GoToUrlAction(url=f'{base_url}/page1', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		action_model = GoToUrlActionModel(**action_data)
		result = await controller.act(action_model, browser_session)

		# Verify the successful navigation result
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert f'Navigated to {base_url}' in result.extracted_content

	async def test_go_to_url_network_error(self, controller, browser_session: BrowserSession):
		"""Test that go_to_url handles network errors gracefully instead of throwing hard errors."""
		# Create action model for go_to_url with an invalid domain
		action_data = {'go_to_url': GoToUrlAction(url='https://www.nonexistentdndbeyond.com/', new_tab=False)}

		# Create the ActionModel instance
		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		action_model = GoToUrlActionModel(**action_data)

		# Execute the action - should return soft error instead of throwing
		result = await controller.act(action_model, browser_session)

		# Verify the result
		assert isinstance(result, ActionResult)
		# The navigation should fail with an error for non-existent domain

		# Test that get_state_summary works
		try:
			await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)
			assert False, 'Expected throw error when navigating to non-existent page'
		except Exception as e:
			pass

		# Test that browser state recovery works after error
		summary = await browser_session.get_browser_state_summary(include_screenshot=False)
		assert summary is not None

	async def test_navigate_to_url_event_directly(self, browser_session, base_url):
		"""Test NavigateToUrlEvent directly through the event bus."""
		from browser_use.browser.events import NavigateToUrlEvent

		# Test navigation to a valid URL
		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/page1'))
		result = await asyncio.wait_for(event, timeout=3.0)
		# NavigateToUrlEvent handlers don't return values, just wait for completion
		assert result is not None

		# Wait a bit for navigation to complete
		await asyncio.sleep(0.5)

		# Verify we're on the correct page
		current_url = await browser_session.get_current_page_url()
		assert f'{base_url}/page1' in current_url

	async def test_go_to_url_new_tab(self, controller, browser_session, base_url):
		"""Test that GoToUrlAction with new_tab=True opens URL in a new tab."""
		# Get initial tab count
		initial_tab_count = len(browser_session.tabs)

		# Navigate to URL in new tab
		action_data = {'go_to_url': GoToUrlAction(url=f'{base_url}/page2', new_tab=True)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		result = await controller.act(GoToUrlActionModel(**action_data), browser_session)
		await asyncio.sleep(0.5)

		# Verify result
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Navigated to' in result.extracted_content

		# Verify new tab was created
		final_tab_count = len(browser_session.tabs)
		assert final_tab_count == initial_tab_count + 1

		# Verify we're on the new page
		current_url = await browser_session.get_current_page_url()
		assert f'{base_url}/page2' in current_url

	async def test_navigate_relative_url(self, controller, browser_session, base_url):
		"""Test navigating using relative URLs."""
		# First navigate to base URL
		action_data = {'go_to_url': GoToUrlAction(url=base_url, new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**action_data), browser_session)

		# Now navigate using relative URL
		relative_action = {'go_to_url': GoToUrlAction(url='/page1', new_tab=False)}
		result = await controller.act(GoToUrlActionModel(**relative_action), browser_session)

		# Verify navigation worked
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None

		# Check we're on the right page
		current_url = await browser_session.get_current_page_url()
		assert f'{base_url}/page1' in current_url

	async def test_navigate_javascript_url(self, controller, browser_session, base_url):
		"""Test that javascript: URLs are handled appropriately."""
		# Navigate to a normal page first
		action_data = {'go_to_url': GoToUrlAction(url=f'{base_url}/page1', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**action_data), browser_session)

		# Try to navigate to javascript: URL (should be handled gracefully)
		js_action = {'go_to_url': GoToUrlAction(url='javascript:alert("test")', new_tab=False)}
		result = await controller.act(GoToUrlActionModel(**js_action), browser_session)

		# Should either succeed or fail gracefully
		assert isinstance(result, ActionResult)

	async def test_navigate_data_url(self, controller, browser_session):
		"""Test navigating to a data: URL."""
		# Create a simple data URL
		data_url = 'data:text/html,<html><head><title>Data URL Test</title></head><body><h1>Data URL Content</h1></body></html>'

		action_data = {'go_to_url': GoToUrlAction(url=data_url, new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		result = await controller.act(GoToUrlActionModel(**action_data), browser_session)

		# Verify navigation
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None

		# Verify we can get the page title
		page = await browser_session.get_current_page()
		title = await page.title()
		assert title == 'Data URL Test'

	async def test_navigate_with_hash(self, controller, browser_session, base_url, http_server):
		"""Test navigating to URLs with hash fragments."""
		# Add a page with anchors
		http_server.expect_request('/page-with-anchors').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head><title>Page with Anchors</title></head>
			<body>
				<h1 id="top">Top of Page</h1>
				<div style="height: 2000px;">Content</div>
				<h2 id="section1">Section 1</h2>
				<div style="height: 1000px;">More content</div>
				<h2 id="section2">Section 2</h2>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to page with hash
		action_data = {'go_to_url': GoToUrlAction(url=f'{base_url}/page-with-anchors#section1', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		result = await controller.act(GoToUrlActionModel(**action_data), browser_session)

		# Verify navigation
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None

		# Verify URL includes hash
		current_url = await browser_session.get_current_page_url()
		assert '#section1' in current_url

	async def test_navigate_with_query_params(self, controller, browser_session, base_url, http_server):
		"""Test navigating to URLs with query parameters."""
		# Add a page that shows query params
		http_server.expect_request('/search').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head><title>Search Page</title></head>
			<body>
				<h1>Search Results</h1>
				<div id="query"></div>
				<script>
					const params = new URLSearchParams(window.location.search);
					document.getElementById('query').textContent = 'Query: ' + params.get('q');
				</script>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate with query parameters
		action_data = {'go_to_url': GoToUrlAction(url=f'{base_url}/search?q=test+query&page=1', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		result = await controller.act(GoToUrlActionModel(**action_data), browser_session)

		# Verify navigation
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None

		# Verify URL includes query params
		current_url = await browser_session.get_current_page_url()
		assert 'q=test+query' in current_url or 'q=test%20query' in current_url
		assert 'page=1' in current_url

	async def test_navigate_multiple_tabs(self, controller, browser_session, base_url):
		"""Test navigating in multiple tabs sequentially."""
		# Navigate to first page in current tab
		action1 = {'go_to_url': GoToUrlAction(url=f'{base_url}/page1', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**action1), browser_session)

		# Open second page in new tab
		action2 = {'go_to_url': GoToUrlAction(url=f'{base_url}/page2', new_tab=True)}
		await controller.act(GoToUrlActionModel(**action2), browser_session)

		# Open home page in yet another new tab
		action3 = {'go_to_url': GoToUrlAction(url=base_url, new_tab=True)}
		await controller.act(GoToUrlActionModel(**action3), browser_session)

		# Should have 3 tabs now
		assert len(browser_session.tabs) == 3

		# Current tab should be the last one opened
		current_url = await browser_session.get_current_page_url()
		assert base_url in current_url and '/page' not in current_url

	async def test_navigate_timeout_handling(self, controller, browser_session):
		"""Test that navigation timeouts are handled gracefully."""
		# Try to navigate to a URL that will likely timeout
		# Using a private IP that's unlikely to respond
		timeout_url = 'http://192.0.2.1:8080/timeout'

		action_data = {'go_to_url': GoToUrlAction(url=timeout_url, new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		# This should complete without hanging indefinitely
		result = await controller.act(GoToUrlActionModel(**action_data), browser_session)

		# Should get a result (possibly with error)
		assert isinstance(result, ActionResult)

	async def test_navigate_redirect(self, controller, browser_session, base_url, http_server):
		"""Test navigating to a URL that redirects."""
		# Add a redirect endpoint
		http_server.expect_request('/redirect').respond_with_data(
			'',
			status=302,
			headers={'Location': f'{base_url}/page2'},
		)

		# Navigate to redirect URL
		action_data = {'go_to_url': GoToUrlAction(url=f'{base_url}/redirect', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		result = await controller.act(GoToUrlActionModel(**action_data), browser_session)

		# Verify navigation succeeded
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None

		# Should end up on page2 after redirect
		await asyncio.sleep(0.5)  # Give redirect time to complete
		current_url = await browser_session.get_current_page_url()
		assert '/page2' in current_url

	async def test_navigate_to_url_event_with_new_tab_and_tab_created_event(self, browser_session, base_url):
		"""Test NavigateToUrlEvent with new_tab=True and verify TabCreatedEvent is emitted."""
		from browser_use.browser.events import NavigateToUrlEvent, TabCreatedEvent

		initial_tab_count = len(browser_session.tabs)

		# Navigate to URL in new tab via direct event
		nav_event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/page2', new_tab=True))
		await nav_event

		# Verify new tab was created
		assert len(browser_session.tabs) == initial_tab_count + 1

		# Check that current page is the new tab
		current_url = await browser_session.get_current_page_url()
		assert f'{base_url}/page2' in current_url

		# Check event history for TabCreatedEvent
		event_history = list(browser_session.event_bus.event_history.values())
		created_events = [e for e in event_history if isinstance(e, TabCreatedEvent)]
		assert len(created_events) >= 1

	async def test_navigate_with_new_tab_focuses_properly(self, browser_session):
		"""Test that NavigateToUrlEvent with new_tab=True properly switches focus."""
		from browser_use.browser.events import NavigateToUrlEvent

		# Get initial state
		initial_tabs_count = len(browser_session.tabs)
		initial_url = await browser_session.get_current_page_url()

		# Navigate to a URL in a new tab
		nav_event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url='https://example.com', new_tab=True))
		await nav_event

		# Small delay to ensure navigation completes
		await asyncio.sleep(1)

		# Get browser state after navigation
		current_url = await browser_session.get_current_page_url()

		# Verify a new tab was created
		assert len(browser_session.tabs) == initial_tabs_count + 1

		# Verify focus switched to the new tab
		assert 'example.com' in current_url
		assert current_url != initial_url

	async def test_navigate_and_verify_page_properties(self, browser_session, base_url):
		"""Test that NavigateToUrlEvent changes the URL and page properties are accessible."""
		from browser_use.browser.events import NavigateToUrlEvent

		# Navigate to the test page
		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/'))
		await event

		# Wait for navigation to complete
		await asyncio.sleep(0.5)

		# Get the current page URL
		current_url = await browser_session.get_current_page_url()

		# Verify the page URL matches what we navigated to
		assert f'{base_url}/' in current_url

		# Get the actual page object
		page = browser_session.page

		# Verify the page title
		title = await page.title()
		assert title == 'Test Home Page'
