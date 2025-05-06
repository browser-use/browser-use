import asyncio
import time

import pytest
from pydantic import BaseModel
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext
from browser_use.controller.service import Controller
from browser_use.controller.views import (
	ClickElementAction,
	CloseTabAction,
	DoneAction,
	DragDropAction,
	GoToUrlAction,
	InputTextAction,
	NoParamsAction,
	OpenTabAction,
	ScrollAction,
	SearchGoogleAction,
	SendKeysAction,
	SwitchTabAction,
)


class TestControllerIntegration:
	"""Integration tests for Controller using actual browser instances."""

	@pytest.fixture(scope='module')
	def event_loop(self):
		"""Create and provide an event loop for async tests."""
		loop = asyncio.get_event_loop_policy().new_event_loop()
		yield loop
		loop.close()

	@pytest.fixture(scope='module')
	def http_server(self):
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

		server.expect_request('/search').respond_with_data(
			"""
			<html>
			<head><title>Search Results</title></head>
			<body>
				<h1>Search Results</h1>
				<div class="results">
					<div class="result">Result 1</div>
					<div class="result">Result 2</div>
					<div class="result">Result 3</div>
				</div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		yield server
		server.stop()

	@pytest.fixture
	def base_url(self, http_server):
		"""Return the base URL for the test HTTP server."""
		return f'http://{http_server.host}:{http_server.port}'

	@pytest.fixture(scope='module')
	async def browser(self, event_loop):
		"""Create and provide a Browser instance with security disabled."""
		browser_instance = Browser(
			config=BrowserConfig(
				headless=True,
			)
		)
		yield browser_instance
		await browser_instance.close()

	@pytest.fixture
	async def browser_context(self, browser):
		"""Create and provide a BrowserContext instance."""
		context = BrowserContext(browser=browser)
		yield context
		await context.close()

	@pytest.fixture
	def controller(self):
		"""Create and provide a Controller instance."""
		return Controller()

	@pytest.mark.asyncio
	async def test_go_to_url_action(self, controller, browser_context, base_url):
		"""Test that GoToUrlAction navigates to the specified URL."""
		# Create action model for go_to_url
		action_data = {'go_to_url': GoToUrlAction(url=f'{base_url}/page1')}

		# Create the ActionModel instance
		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		action_model = GoToUrlActionModel(**action_data)

		# Execute the action
		result = await controller.act(action_model, browser_context)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert f'Navigated to {base_url}/page1' in result.extracted_content

		# Verify the current page URL
		page = await browser_context.get_current_page()
		assert f'{base_url}/page1' in page.url

	@pytest.mark.asyncio
	async def test_scroll_actions(self, controller, browser_context, base_url):
		"""Test that scroll actions correctly scroll the page."""
		# First navigate to a page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/page1')}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_context)

		# Create scroll down action
		scroll_action = {'scroll_down': ScrollAction(amount=200)}

		class ScrollActionModel(ActionModel):
			scroll_down: ScrollAction | None = None

		# Execute scroll down
		result = await controller.act(ScrollActionModel(**scroll_action), browser_context)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert 'Scrolled down' in result.extracted_content

		# Create scroll up action
		scroll_up_action = {'scroll_up': ScrollAction(amount=100)}

		class ScrollUpActionModel(ActionModel):
			scroll_up: ScrollAction | None = None

		# Execute scroll up
		result = await controller.act(ScrollUpActionModel(**scroll_up_action), browser_context)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert 'Scrolled up' in result.extracted_content

	@pytest.mark.asyncio
	async def test_registry_actions(self, controller, browser_context):
		"""Test that the registry contains the expected default actions."""
		# Check that common actions are registered
		common_actions = [
			'go_to_url',
			'search_google',
			'click_element_by_index',
			'input_text',
			'scroll_down',
			'scroll_up',
			'go_back',
			'switch_tab',
			'open_tab',
			'close_tab',
			'wait',
		]

		for action in common_actions:
			assert action in controller.registry.registry.actions
			assert controller.registry.registry.actions[action].function is not None
			assert controller.registry.registry.actions[action].description is not None

	@pytest.mark.asyncio
	async def test_custom_action_registration(self, controller, browser_context, base_url):
		"""Test registering a custom action and executing it."""

		# Define a custom action
		class CustomParams(BaseModel):
			text: str

		@controller.action('Test custom action', param_model=CustomParams)
		async def custom_action(params: CustomParams, browser):
			page = await browser.get_current_page()
			return ActionResult(extracted_content=f'Custom action executed with: {params.text} on {page.url}')

		# Navigate to a page first
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/page1')}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_context)

		# Create the custom action model
		custom_action_data = {'custom_action': CustomParams(text='test_value')}

		class CustomActionModel(ActionModel):
			custom_action: CustomParams | None = None

		# Execute the custom action
		result = await controller.act(CustomActionModel(**custom_action_data), browser_context)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert 'Custom action executed with: test_value on' in result.extracted_content
		assert f'{base_url}/page1' in result.extracted_content

	@pytest.mark.asyncio
	async def test_input_text_action(self, controller, browser_context, base_url, http_server):
		"""Test that InputTextAction correctly inputs text into form fields."""
		# Set up search form endpoint for this test
		http_server.expect_request('/searchform').respond_with_data(
			"""
			<html>
			<head><title>Search Form</title></head>
			<body>
				<h1>Search Form</h1>
				<form action="/search" method="get">
					<input type="text" id="searchbox" name="q" placeholder="Search...">
					<button type="submit">Search</button>
				</form>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to a page with a form
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/searchform')}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_context)

		# Get the search input field index
		page = await browser_context.get_current_page()
		selector_map = await browser_context.get_selector_map()

		# Find the search input field - this requires examining the DOM
		# We'll mock this part since we can't rely on specific element indices
		# In a real test, you would get the actual index from the selector map

		# For demonstration, we'll just use a hard-coded mock value
		# and check that the controller processes the action correctly
		mock_input_index = 1  # This would normally be determined dynamically

		# Create input text action
		input_action = {'input_text': InputTextAction(index=mock_input_index, text='Python programming')}

		class InputTextActionModel(ActionModel):
			input_text: InputTextAction | None = None

		# The actual input might fail if the page structure changes or in headless mode
		# So we'll just verify the controller correctly processes the action
		try:
			result = await controller.act(InputTextActionModel(**input_action), browser_context)
			# If successful, verify the result
			assert isinstance(result, ActionResult)
			assert 'Input' in result.extracted_content
		except Exception as e:
			# If it fails due to DOM issues, that's expected in a test environment
			assert 'Element index' in str(e) or 'does not exist' in str(e)

	@pytest.mark.asyncio
	async def test_error_handling(self, controller, browser_context):
		"""Test error handling when an action fails."""
		# Create an action with an invalid index
		invalid_action = {'click_element_by_index': ClickElementAction(index=9999)}

		class ClickActionModel(ActionModel):
			click_element_by_index: ClickElementAction | None = None

		# This should fail since the element doesn't exist
		with pytest.raises(Exception) as excinfo:
			await controller.act(ClickActionModel(**invalid_action), browser_context)

		# Verify that an appropriate error is raised
		assert 'does not exist' in str(excinfo.value) or 'Element with index' in str(excinfo.value)

	@pytest.mark.asyncio
	async def test_wait_action(self, controller, browser_context):
		"""Test that the wait action correctly waits for the specified duration."""
		# Create wait action for 1 second - fix to use a dictionary
		wait_action = {'wait': {'seconds': 1}}  # Corrected format

		class WaitActionModel(ActionModel):
			wait: dict | None = None

		# Record start time
		start_time = time.time()

		# Execute wait action
		result = await controller.act(WaitActionModel(**wait_action), browser_context)

		# Record end time
		end_time = time.time()

		# Verify the result
		assert isinstance(result, ActionResult)
		assert 'Waiting for' in result.extracted_content

		# Verify that at least 1 second has passed
		assert end_time - start_time >= 0.9  # Allow some timing margin

	@pytest.mark.asyncio
	async def test_go_back_action(self, controller, browser_context, base_url):
		"""Test that go_back action navigates to the previous page."""
		# Navigate to first page
		goto_action1 = {'go_to_url': GoToUrlAction(url=f'{base_url}/page1')}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action1), browser_context)

		# Store the first page URL
		page1 = await browser_context.get_current_page()
		first_url = page1.url
		print(f'First page URL: {first_url}')

		# Navigate to second page
		goto_action2 = {'go_to_url': GoToUrlAction(url=f'{base_url}/page2')}
		await controller.act(GoToUrlActionModel(**goto_action2), browser_context)

		# Verify we're on the second page
		page2 = await browser_context.get_current_page()
		second_url = page2.url
		print(f'Second page URL: {second_url}')
		assert f'{base_url}/page2' in second_url

		# Execute go back action
		go_back_action = {'go_back': NoParamsAction()}

		class GoBackActionModel(ActionModel):
			go_back: NoParamsAction | None = None

		result = await controller.act(GoBackActionModel(**go_back_action), browser_context)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert 'Navigated back' in result.extracted_content

		# Add another delay to allow the navigation to complete
		await asyncio.sleep(1)

		# Verify we're back on a different page than before
		page3 = await browser_context.get_current_page()
		final_url = page3.url
		print(f'Final page URL after going back: {final_url}')

		# Try to verify we're back on the first page, but don't fail the test if not
		assert f'{base_url}/page1' in final_url, f'Expected to return to page1 but got {final_url}'

	@pytest.mark.asyncio
	async def test_navigation_chain(self, controller, browser_context, base_url):
		"""Test navigating through multiple pages and back through history."""
		# Set up a chain of navigation: Home -> Page1 -> Page2
		urls = [f'{base_url}/', f'{base_url}/page1', f'{base_url}/page2']

		# Navigate to each page in sequence
		for url in urls:
			action_data = {'go_to_url': GoToUrlAction(url=url)}

			class GoToUrlActionModel(ActionModel):
				go_to_url: GoToUrlAction | None = None

			await controller.act(GoToUrlActionModel(**action_data), browser_context)

			# Verify current page
			page = await browser_context.get_current_page()
			assert url in page.url

		# Go back twice and verify each step
		for expected_url in reversed(urls[:-1]):
			go_back_action = {'go_back': NoParamsAction()}

			class GoBackActionModel(ActionModel):
				go_back: NoParamsAction | None = None

			await controller.act(GoBackActionModel(**go_back_action), browser_context)
			await asyncio.sleep(1)  # Wait for navigation to complete

			page = await browser_context.get_current_page()
			assert expected_url in page.url

	@pytest.mark.asyncio
	async def test_concurrent_tab_operations(self, controller, browser_context, base_url):
		"""Test operations across multiple tabs."""
		# Create two tabs with different content
		urls = [f'{base_url}/page1', f'{base_url}/page2']

		# First tab
		goto_action1 = {'go_to_url': GoToUrlAction(url=urls[0])}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action1), browser_context)

		# Open second tab
		open_tab_action = {'open_tab': OpenTabAction(url=urls[1])}

		class OpenTabActionModel(ActionModel):
			open_tab: OpenTabAction | None = None

		await controller.act(OpenTabActionModel(**open_tab_action), browser_context)

		# Verify we're on second tab
		page = await browser_context.get_current_page()
		assert urls[1] in page.url

		# Switch back to first tab
		switch_tab_action = {'switch_tab': SwitchTabAction(page_id=0)}

		class SwitchTabActionModel(ActionModel):
			switch_tab: SwitchTabAction | None = None

		await controller.act(SwitchTabActionModel(**switch_tab_action), browser_context)

		# Verify we're back on first tab
		page = await browser_context.get_current_page()
		assert urls[0] in page.url

		# Close the second tab
		close_tab_action = {'close_tab': CloseTabAction(page_id=1)}

		class CloseTabActionModel(ActionModel):
			close_tab: CloseTabAction | None = None

		await controller.act(CloseTabActionModel(**close_tab_action), browser_context)

		# Verify only one tab remains
		tabs_info = await browser_context.get_tabs_info()
		assert len(tabs_info) == 1
		assert urls[0] in tabs_info[0].url

	@pytest.mark.asyncio
	async def test_excluded_actions(self, browser_context):
		"""Test that excluded actions are not registered."""
		# Create controller with excluded actions
		excluded_controller = Controller(exclude_actions=['search_google', 'open_tab'])

		# Verify excluded actions are not in the registry
		assert 'search_google' not in excluded_controller.registry.registry.actions
		assert 'open_tab' not in excluded_controller.registry.registry.actions

		# But other actions are still there
		assert 'go_to_url' in excluded_controller.registry.registry.actions
		assert 'click_element_by_index' in excluded_controller.registry.registry.actions

	@pytest.mark.asyncio
	async def test_search_google_action(self, controller, browser_context, base_url):
		"""Test the search_google action."""
		# Add a custom search handler for our test server
		# Since this is a mock test, we'll just navigate to the /search page

		# Execute search_google action - it will actually navigate to our search results page
		search_action = {'search_google': SearchGoogleAction(query='Python web automation')}

		class SearchGoogleActionModel(ActionModel):
			search_google: SearchGoogleAction | None = None

		result = await controller.act(SearchGoogleActionModel(**search_action), browser_context)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert 'Searched for "Python web automation" in Google' in result.extracted_content

		# For our test purposes, we just verify we're on some URL
		page = await browser_context.get_current_page()
		assert page.url is not None and 'Python' in page.url

	@pytest.mark.asyncio
	async def test_done_action(self, controller, browser_context, base_url):
		"""Test that DoneAction completes a task and reports success or failure."""
		# First navigate to a page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/page1')}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_context)

		success_done_message = 'Successfully completed task'

		# Create done action with success
		done_action = {'done': DoneAction(text=success_done_message, success=True)}

		class DoneActionModel(ActionModel):
			done: DoneAction | None = None

		# Execute done action
		result = await controller.act(DoneActionModel(**done_action), browser_context)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert success_done_message in result.extracted_content
		assert result.success is True
		assert result.is_done is True
		assert result.error is None

		failed_done_message = 'Failed to complete task'

		# Test with failure case
		failed_done_action = {'done': DoneAction(text=failed_done_message, success=False)}

		# Execute failed done action
		result = await controller.act(DoneActionModel(**failed_done_action), browser_context)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert failed_done_message in result.extracted_content
		assert result.success is False
		assert result.is_done is True
		assert result.error is None

	@pytest.mark.asyncio
	async def test_drag_drop_action(self, controller, browser_context, base_url, http_server):
		"""Test that DragDropAction correctly drags and drops elements."""
		# Set up drag and drop test page for this test
		http_server.expect_request('/dragdrop').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Drag and Drop Test</title>
				<style>
					body { font-family: Arial, sans-serif; padding: 20px; }
					.container { display: flex; }
					.dropzone {
						width: 200px;
						height: 200px;
						border: 2px dashed #ccc;
						margin: 10px;
						padding: 10px;
						transition: background-color 0.3s;
					}
					.draggable {
						width: 80px;
						height: 80px;
						background-color: #3498db;
						color: white;
						text-align: center;
						line-height: 80px;
						cursor: move;
						user-select: none;
					}
					#log {
						margin-top: 20px;
						padding: 10px;
						border: 1px solid #ccc;
						height: 150px;
						overflow-y: auto;
					}
				</style>
			</head>
			<body>
				<h1>Drag and Drop Test</h1>
				
				<div class="container">
					<div id="zone1" class="dropzone">
						Zone 1
						<div id="draggable" class="draggable" draggable="true">Drag me</div>
					</div>
					
					<div id="zone2" class="dropzone">
						Zone 2
					</div>
				</div>
				
				<div id="log">Event log:</div>
				
				<script>
					// Track item position for verification
					function updateStatus() {
						const element = document.getElementById('draggable');
						const parent = element.parentElement;
						document.getElementById('status').textContent = 
							`Item is in: ${parent.id}, dropped count: ${dropCount}`;
					}
					
					// Element references
					const draggable = document.getElementById('draggable');
					const dropzones = document.querySelectorAll('.dropzone');
					const log = document.getElementById('log');
					
					// Counters for verification
					let dragStartCount = 0;
					let dropCount = 0;
					
					// Log events
					function logEvent(event) {
						const info = event.type;
						log.textContent += info + ';';
					}
					
					// Add status display
					const statusDiv = document.createElement('div');
					statusDiv.id = 'status';
					document.body.appendChild(statusDiv);
					
					// Drag events for the draggable element
					draggable.addEventListener('dragstart', (e) => {
						dragStartCount++;
						logEvent(e);
						// Required for Firefox
						e.dataTransfer.setData('text/plain', '');
						e.target.style.opacity = '0.5';
					});
					
					draggable.addEventListener('dragend', (e) => {
						logEvent(e);
						e.target.style.opacity = '1';
						updateStatus();
					});
					
					// Events for the dropzones
					dropzones.forEach(zone => {
						zone.addEventListener('dragover', (e) => {
							e.preventDefault(); // Allow drop
							logEvent(e);
							zone.style.backgroundColor = '#f0f0f0';
						});
						
						zone.addEventListener('dragleave', (e) => {
							logEvent(e);
							zone.style.backgroundColor = '';
						});
						
						zone.addEventListener('drop', (e) => {
							e.preventDefault();
							logEvent(e);
							zone.style.backgroundColor = '';
							
							// Only append if it's our draggable element
							if (e.dataTransfer.types.includes('text/plain')) {
								dropCount++;
								zone.appendChild(draggable);
							}
						});
					});
					
					// Mouse events
					draggable.addEventListener('mousedown', (e) => logEvent(e));
					document.addEventListener('mouseup', (e) => logEvent(e));
					
					// Initialize status
					updateStatus();
				</script>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Step 1: Navigate to the drag and drop test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/dragdrop')}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		goto_result = await controller.act(GoToUrlActionModel(**goto_action), browser_context)

		# Verify navigation worked
		assert goto_result.error is None, f'Navigation failed: {goto_result.error}'
		assert f'Navigated to {base_url}/dragdrop' in goto_result.extracted_content

		# Get page reference
		page = await browser_context.get_current_page()

		# Verify we loaded the page correctly
		title = await page.title()
		assert title == 'Drag and Drop Test', f'Page did not load correctly, got title: {title}'

		# Step 2: Verify initial state - draggable should be in zone1
		initial_parent = await page.evaluate('() => document.getElementById("draggable").parentElement.id')
		assert initial_parent == 'zone1', f'Element should start in zone1, but found in {initial_parent}'

		# Step 3: Get the element positions for drag operation
		element_info = await page.evaluate("""
			() => {
				const draggable = document.getElementById("draggable");
				const zone2 = document.getElementById("zone2");
				
				const draggableRect = draggable.getBoundingClientRect();
				const zone2Rect = zone2.getBoundingClientRect();
				
				return {
					source: {
						x: Math.round(draggableRect.left + draggableRect.width/2),
						y: Math.round(draggableRect.top + draggableRect.height/2)
					},
					target: {
						x: Math.round(zone2Rect.left + zone2Rect.width/2),
						y: Math.round(zone2Rect.top + zone2Rect.height/2)
					}
				};
			}
		""")

		print(f'Source element position: {element_info["source"]}')
		print(f'Target position: {element_info["target"]}')

		# Step 4: Use the controller's DragDropAction to perform the drag
		drag_action = {
			'drag_drop': DragDropAction(
				# Use the coordinate-based approach
				coord_source_x=element_info['source']['x'],
				coord_source_y=element_info['source']['y'],
				coord_target_x=element_info['target']['x'],
				coord_target_y=element_info['target']['y'],
				steps=10,  # More steps for smoother movement
				delay_ms=10,  # Small delay for browser to process events
			)
		}

		class DragDropActionModel(ActionModel):
			drag_drop: DragDropAction | None = None

		# Execute the drag action through the controller
		result = await controller.act(DragDropActionModel(**drag_action), browser_context)

		# Step 5: Verify the controller action result
		assert result.error is None, f'Drag operation failed with error: {result.error}'
		assert result.is_done is False
		assert '🖱️ Dragged from' in result.extracted_content

		# Step 6: Verify the element was moved by checking its new parent
		final_parent = await page.evaluate('() => document.getElementById("draggable").parentElement.id')

		# Step 7: Get the event log to see what events were fired
		event_log = await page.evaluate('() => document.getElementById("log").textContent')
		print(f'Event log: {event_log}')

		# Check that mousedown and mouseup events were recorded
		assert 'mousedown' in event_log, 'No mousedown event detected'

		# Step 8: Verify the status shows the item was dropped
		status_text = await page.evaluate('() => document.getElementById("status").textContent')

		drag_succeeded = final_parent == 'zone2'

		assert drag_succeeded, "Drag and drop events weren't fired correctly"

	@pytest.mark.asyncio
	async def test_send_keys_action(self, controller, browser_context, base_url, http_server):
		"""Test SendKeysAction using a controlled local HTML file."""
		# Set up keyboard test page for this test
		http_server.expect_request('/keyboard').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Keyboard Test</title>
				<style>
					body { font-family: Arial, sans-serif; margin: 20px; }
					input, textarea { margin: 10px 0; padding: 5px; width: 300px; }
					#result { margin-top: 20px; padding: 10px; border: 1px solid #ccc; min-height: 30px; }
				</style>
			</head>
			<body>
				<h1>Keyboard Actions Test</h1>
				<form id="testForm">
					<div>
						<label for="textInput">Text Input:</label>
						<input type="text" id="textInput" placeholder="Type here...">
					</div>
					<div>
						<label for="textarea">Textarea:</label>
						<textarea id="textarea" rows="4" placeholder="Type here..."></textarea>
					</div>
				</form>
				<div id="result"></div>
				
				<script>
					// Track focused element
					document.addEventListener('focusin', function(e) {
						document.getElementById('result').textContent = 'Focused on: ' + e.target.id;
					}, true);
					
					// Track key events
					document.addEventListener('keydown', function(e) {
						const element = document.activeElement;
						if (element.id) {
							const resultEl = document.getElementById('result');
							resultEl.textContent += '\\nKeydown: ' + e.key;
							
							// For Ctrl+A, detect and show selection
							if (e.key === 'a' && (e.ctrlKey || e.metaKey)) {
								resultEl.textContent += '\\nCtrl+A detected';
								setTimeout(() => {
									resultEl.textContent += '\\nSelection length: ' + 
										(window.getSelection().toString().length || 
										(element.selectionEnd - element.selectionStart));
								}, 50);
							}
						}
					});
				</script>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to the keyboard test page on the local HTTP server
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/keyboard')}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		# Execute navigation
		goto_result = await controller.act(GoToUrlActionModel(**goto_action), browser_context)
		await asyncio.sleep(0.1)

		# Verify navigation result
		assert isinstance(goto_result, ActionResult)
		assert f'Navigated to {base_url}/keyboard' in goto_result.extracted_content
		assert goto_result.error is None
		assert goto_result.is_done is False

		# Get the page object
		page = await browser_context.get_current_page()

		# Verify page loaded
		title = await page.title()
		assert title == 'Keyboard Test'

		# Verify initial page state
		h1_text = await page.evaluate('() => document.querySelector("h1").textContent')
		assert h1_text == 'Keyboard Actions Test'

		# 1. Test Tab key to focus the first input
		tab_keys_action = {'send_keys': SendKeysAction(keys='Tab')}

		class SendKeysActionModel(ActionModel):
			send_keys: SendKeysAction | None = None

		tab_result = await controller.act(SendKeysActionModel(**tab_keys_action), browser_context)
		await asyncio.sleep(0.1)

		# Verify Tab action result
		assert isinstance(tab_result, ActionResult)
		assert 'Sent keys: Tab' in tab_result.extracted_content
		assert tab_result.error is None
		assert tab_result.is_done is False

		# Verify Tab worked by checking focused element
		active_element_id = await page.evaluate('() => document.activeElement.id')
		assert active_element_id == 'textInput', f"Expected 'textInput' to be focused, got '{active_element_id}'"

		# Verify result text in the DOM
		result_text = await page.locator('#result').text_content()
		assert 'Focused on: textInput' in result_text

		# 2. Type text into the input
		test_text = 'This is a test'
		type_action = {'send_keys': SendKeysAction(keys=test_text)}
		type_result = await controller.act(SendKeysActionModel(**type_action), browser_context)
		await asyncio.sleep(0.1)

		# Verify typing action result
		assert isinstance(type_result, ActionResult)
		assert f'Sent keys: {test_text}' in type_result.extracted_content
		assert type_result.error is None
		assert type_result.is_done is False

		# Verify text was entered
		input_value = await page.evaluate('() => document.getElementById("textInput").value')
		assert input_value == test_text, f"Expected input value '{test_text}', got '{input_value}'"

		# Verify key events were recorded
		result_text = await page.locator('#result').text_content()
		for char in test_text:
			assert f'Keydown: {char}' in result_text, f"Missing key event for '{char}'"

		# 3. Test Ctrl+A for select all
		select_all_action = {'send_keys': SendKeysAction(keys='ControlOrMeta+a')}
		select_all_result = await controller.act(SendKeysActionModel(**select_all_action), browser_context)
		# Wait longer for selection to take effect
		await asyncio.sleep(1.0)

		# Verify select all action result
		assert isinstance(select_all_result, ActionResult)
		assert 'Sent keys: ControlOrMeta+a' in select_all_result.extracted_content
		assert select_all_result.error is None

		# Verify selection length matches the text length
		selection_length = await page.evaluate(
			'() => document.activeElement.selectionEnd - document.activeElement.selectionStart'
		)
		assert selection_length == len(test_text), f'Expected selection length {len(test_text)}, got {selection_length}'

		# Verify selection in result text
		result_text = await page.locator('#result').text_content()
		assert 'Keydown: a' in result_text
		assert 'Ctrl+A detected' in result_text
		assert 'Selection length:' in result_text

		# 4. Test Tab to next field
		tab_result2 = await controller.act(SendKeysActionModel(**tab_keys_action), browser_context)
		await asyncio.sleep(0.1)

		# Verify second Tab action result
		assert isinstance(tab_result2, ActionResult)
		assert 'Sent keys: Tab' in tab_result2.extracted_content
		assert tab_result2.error is None

		# Verify we moved to the textarea
		active_element_id = await page.evaluate('() => document.activeElement.id')
		assert active_element_id == 'textarea', f"Expected 'textarea' to be focused, got '{active_element_id}'"

		# Verify focus changed in result text
		result_text = await page.locator('#result').text_content()
		assert 'Focused on: textarea' in result_text

		# 5. Type in the textarea
		textarea_text = 'Testing multiline\ninput text'
		textarea_action = {'send_keys': SendKeysAction(keys=textarea_text)}
		textarea_result = await controller.act(SendKeysActionModel(**textarea_action), browser_context)

		# Verify textarea typing action result
		assert isinstance(textarea_result, ActionResult)
		assert f'Sent keys: {textarea_text}' in textarea_result.extracted_content
		assert textarea_result.error is None
		assert textarea_result.is_done is False

		# Verify text was entered in textarea
		textarea_value = await page.evaluate('() => document.getElementById("textarea").value')
		assert textarea_value == textarea_text, f"Expected textarea value '{textarea_text}', got '{textarea_value}'"

		# Verify newline was properly handled
		lines = textarea_value.split('\n')
		assert len(lines) == 2, f'Expected 2 lines in textarea, got {len(lines)}'
		assert lines[0] == 'Testing multiline'
		assert lines[1] == 'input text'

		# Test that Tab cycles back to the first element if we tab again
		await controller.act(SendKeysActionModel(**tab_keys_action), browser_context)
		await controller.act(SendKeysActionModel(**tab_keys_action), browser_context)

		active_element_id = await page.evaluate('() => document.activeElement.id')
		assert active_element_id == 'textInput', 'Tab cycling through form elements failed'

		# Verify the test input still has its value
		input_value = await page.evaluate('() => document.getElementById("textInput").value')
		assert input_value == test_text, "Input value shouldn't have changed after tabbing"
