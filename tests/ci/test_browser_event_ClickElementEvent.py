import asyncio
import tempfile
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.controller.service import Controller
from browser_use.controller.views import (
	ClickElementAction,
	GoToUrlAction,
	UploadFileAction,
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
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
		)
	)
	await browser_session.start()
	yield browser_session
	await browser_session.kill()


@pytest.fixture(scope='function')
def controller():
	"""Create and provide a Controller instance."""
	return Controller()


class TestClickElementEvent:
	"""Test cases for ClickElementEvent and click_element_by_index action."""

	async def test_error_handling(self, controller, browser_session):
		"""Test error handling when an action fails."""
		# Create an action with an invalid index
		invalid_action = {'click_element_by_index': ClickElementAction(index=999)}  # doesn't exist on page

		from browser_use.agent.views import ActionModel

		class ClickActionModel(ActionModel):
			click_element_by_index: ClickElementAction | None = None

		# This should fail since the element doesn't exist
		result: ActionResult = await controller.act(ClickActionModel(**invalid_action), browser_session)

		assert result.error is not None

	async def test_click_element_by_index(self, controller, browser_session, base_url, http_server):
		"""Test that click_element_by_index correctly clicks an element and handles different outcomes."""
		# Add route for clickable elements test page
		http_server.expect_request('/clickable').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Click Test</title>
				<style>
					.clickable {
						margin: 10px;
						padding: 10px;
						border: 1px solid #ccc;
						cursor: pointer;
					}
					#result {
						margin-top: 20px;
						padding: 10px;
						border: 1px solid #ddd;
						min-height: 20px;
					}
				</style>
			</head>
			<body>
				<h1>Click Test</h1>
				<div class="clickable" id="button1" onclick="updateResult('Button 1 clicked')">Button 1</div>
				<div class="clickable" id="button2" onclick="updateResult('Button 2 clicked')">Button 2</div>
				<a href="#" class="clickable" id="link1" onclick="updateResult('Link 1 clicked'); return false;">Link 1</a>
				<div id="result"></div>
				
				<script>
					function updateResult(text) {
						document.getElementById('result').textContent = text;
					}
				</script>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to the clickable elements test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/clickable', new_tab=False)}

		from browser_use.agent.views import ActionModel

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)

		# Wait for the page to load
		await asyncio.sleep(0.5)  # Give page time to load

		# Initialize the DOM state to populate the selector map
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)

		# Get the selector map
		selector_map = await browser_session.get_selector_map()

		# Find a clickable element in the selector map
		button_index = None
		button_text = None

		for idx, element in selector_map.items():
			# Look for the first div with class "clickable"
			if element.tag_name.lower() == 'div' and 'clickable' in str(element.attributes.get('class', '')):
				button_index = idx
				button_text = element.get_all_children_text(max_depth=2).strip()
				break

		# Verify we found a clickable element
		assert button_index is not None, (
			f'Could not find clickable element in selector map. Available elements: {[f"{idx}: {element.tag_name}" for idx, element in selector_map.items()]}'
		)

		# Define expected test data
		expected_button_text = 'Button 1'
		expected_result_text = 'Button 1 clicked'

		# Verify the button text matches what we expect
		assert button_text is not None and expected_button_text in button_text, (
			f"Expected button text '{expected_button_text}' not found in '{button_text}'"
		)

		# Create a model for the click_element_by_index action
		class ClickElementActionModel(ActionModel):
			click_element_by_index: ClickElementAction | None = None

		# Execute the action with the button index
		result = await controller.act(
			ClickElementActionModel(click_element_by_index=ClickElementAction(index=button_index)), browser_session
		)

		# Verify the result structure
		assert isinstance(result, ActionResult), 'Result should be an ActionResult instance'
		assert result.error is None, f'Expected no error but got: {result.error}'

		# Core logic validation: Verify click was successful
		assert result.extracted_content is not None
		assert f'Clicked element with index {button_index}' in result.extracted_content, (
			f'Expected click confirmation in result content, got: {result.extracted_content}'
		)
		# Note: The click action doesn't include button text in the result, only the index

		# Verify the click actually had an effect on the page using CDP
		cdp_session = await browser_session.get_or_create_cdp_session()
		result_js = await browser_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('result').textContent", 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		result_text = result_js.get('result', {}).get('value', '')
		assert result_text == expected_result_text, f"Expected result text '{expected_result_text}', got '{result_text}'"

	async def test_click_element_new_tab(self, controller, browser_session, base_url, http_server):
		"""Test that click_element_by_index with while_holding_ctrl=True opens links in new tabs."""
		# Add route for new tab test page
		http_server.expect_request('/newTab').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>New Tab Test</title>
			</head>
			<body>
				<h1>New Tab Test</h1>
				<a href="/page1" id="testLink">Open Page 1</a>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to the new tab test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/newTab', new_tab=False)}

		from browser_use.agent.views import ActionModel

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)
		await asyncio.sleep(1)  # Wait for page to load

		# Count initial tabs
		tabs = await browser_session.get_tabs()
		initial_tab_count = len(tabs)

		# Get the link element (assuming it will be at index 0)
		# First get the browser state to see what elements are available
		state = await browser_session.get_browser_state_summary()

		# Find the link element in the selector map
		link_index = None
		for index, element in state.dom_state.selector_map.items():
			if hasattr(element, 'tag_name') and element.tag_name == 'a':
				link_index = index
				break

		assert link_index is not None, 'Could not find link element'

		# Click the link with while_holding_ctrl=True
		click_action = {'click_element_by_index': ClickElementAction(index=link_index, while_holding_ctrl=True)}

		class ClickActionModel(ActionModel):
			click_element_by_index: ClickElementAction | None = None

		result = await controller.act(ClickActionModel(**click_action), browser_session)
		await asyncio.sleep(1)  # Wait for new tab to open

		# Verify the result
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None

		# Verify that a new tab was opened
		tabs = await browser_session.get_tabs()
		final_tab_count = len(tabs)
		assert final_tab_count == initial_tab_count + 1, f'Expected {initial_tab_count + 1} tabs, got {final_tab_count}'

		# Verify we're still on the original tab (not switched) - matches browser Cmd/Ctrl+click behavior
		current_url = await browser_session.get_current_page_url()
		assert f'{base_url}/newTab' in current_url, f'Should still be on original tab, but got {current_url}'

		# Wait for the new tab to finish navigating to the target URL
		# New tabs initially open at the current URL then navigate to the target
		max_wait = 5
		for _ in range(max_wait):
			await asyncio.sleep(0.5)
			tabs = await browser_session.get_tabs()
			new_tab = tabs[-1]  # Last tab is the newly opened one
			if f'{base_url}/page1' in new_tab.url:
				break

		# Verify the new tab has the correct URL
		assert f'{base_url}/page1' in new_tab.url, f'New tab should have page1 URL, but got {new_tab.url}'

	async def test_click_element_normal_vs_new_tab(self, controller, browser_session, base_url, http_server):
		"""Test that click_element_by_index behaves differently with while_holding_ctrl=False vs while_holding_ctrl=True."""
		# Add route for comparison test page
		http_server.expect_request('/comparison').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Comparison Test</title>
			</head>
			<body>
				<h1>Comparison Test</h1>
				<a href="/page2" id="normalLink">Normal Link</a>
				<a href="/page1" id="newTabLink">New Tab Link</a>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to the comparison test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/comparison', new_tab=False)}

		from browser_use.agent.views import ActionModel

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)
		await asyncio.sleep(1)

		tabs = await browser_session.get_tabs()
		initial_tab_count = len(tabs)

		# Get browser state and find link elements
		state = await browser_session.get_browser_state_summary()
		link_indices = []
		for index, element in state.dom_state.selector_map.items():
			if hasattr(element, 'tag_name') and element.tag_name == 'a':
				link_indices.append(index)

		assert len(link_indices) >= 2, 'Need at least 2 links for comparison test'

		# Test normal click (while_holding_ctrl=False) - should navigate in current tab
		click_action_normal = {'click_element_by_index': ClickElementAction(index=link_indices[0], while_holding_ctrl=False)}

		class ClickActionModel(ActionModel):
			click_element_by_index: ClickElementAction | None = None

		result = await controller.act(ClickActionModel(**click_action_normal), browser_session)
		await asyncio.sleep(1)

		# Should still have same number of tabs
		tabs = await browser_session.get_tabs()
		assert len(tabs) == initial_tab_count

		# Navigate back to comparison page for second test
		await controller.act(GoToUrlActionModel(**goto_action), browser_session)
		await asyncio.sleep(1)

		# Test new tab click (while_holding_ctrl=True) - should open in new background tab
		click_action_new_tab = {'click_element_by_index': ClickElementAction(index=link_indices[1], while_holding_ctrl=True)}
		result = await controller.act(ClickActionModel(**click_action_new_tab), browser_session)
		await asyncio.sleep(1)

		# Should have one more tab
		tabs = await browser_session.get_tabs()
		assert len(tabs) == initial_tab_count + 1

	async def test_inline_element_mostly_offscreen(self, controller, browser_session, base_url, http_server):
		"""Test clicking an inline element that's mostly outside the viewport."""
		# Add route for test page with inline element extending beyond viewport
		http_server.expect_request('/inline_offscreen').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Inline Offscreen Test</title>
				<style>
					body { margin: 0; padding: 20px; }
					.container { position: relative; width: 200%; }
					.inline-link {
						display: inline;
						position: absolute;
						left: -100px;
						width: 500px;
						padding: 10px;
						background: #007bff;
						color: white;
						cursor: pointer;
					}
					#result { margin-top: 100px; }
				</style>
			</head>
			<body>
				<div class="container">
					<span class="inline-link" onclick="document.getElementById('result').textContent = 'Inline clicked'">
						This is a very long inline element that extends way beyond the viewport edge
					</span>
				</div>
				<div id="result">Not clicked</div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to the page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/inline_offscreen', new_tab=False)}

		from browser_use.agent.views import ActionModel

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)
		await asyncio.sleep(0.5)

		# Get the clickable elements
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)
		selector_map = await browser_session.get_selector_map()

		# Find the inline element
		inline_index = None
		for idx, element in selector_map.items():
			if 'inline-link' in str(element.attributes.get('class', '')):
				inline_index = idx
				break

		assert inline_index is not None, 'Could not find inline element'

		# Click the element - should click the visible portion
		class ClickActionModel(ActionModel):
			click_element_by_index: ClickElementAction | None = None

		result = await controller.act(
			ClickActionModel(click_element_by_index=ClickElementAction(index=inline_index)), browser_session
		)

		assert result.error is None, f'Click failed: {result.error}'

		# Verify click worked using CDP
		cdp_session = await browser_session.get_or_create_cdp_session()
		result_js = await browser_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('result').textContent", 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		assert result_js.get('result', {}).get('value') == 'Inline clicked'

	async def test_block_inside_inline_multiline(self, controller, browser_session, base_url, http_server):
		"""Test clicking a block element inside an inline element that spans multiple lines."""
		# Add route for complex nested layout
		http_server.expect_request('/block_in_inline').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Block in Inline Test</title>
				<style>
					body { margin: 20px; width: 300px; }
					.inline-wrapper {
						display: inline;
						background: #f0f0f0;
						line-height: 1.5;
					}
					.block-inside {
						display: block;
						margin: 10px 0;
						padding: 10px;
						background: #007bff;
						color: white;
						cursor: pointer;
					}
					#result { margin-top: 50px; }
				</style>
			</head>
			<body>
				<span class="inline-wrapper">
					This is some text that wraps around and contains
					<div class="block-inside" onclick="document.getElementById('result').textContent = 'Block clicked'">
						Click this block element
					</div>
					and continues after the block element with more text that will wrap to multiple lines
				</span>
				<div id="result">Not clicked</div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to the page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/block_in_inline', new_tab=False)}

		from browser_use.agent.views import ActionModel

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)
		await asyncio.sleep(0.5)

		# Get the clickable elements
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)
		selector_map = await browser_session.get_selector_map()

		# Find the block element inside inline
		block_index = None
		for idx, element in selector_map.items():
			if 'block-inside' in str(element.attributes.get('class', '')):
				block_index = idx
				break

		assert block_index is not None, 'Could not find block element'

		# Click the block element
		class ClickActionModel(ActionModel):
			click_element_by_index: ClickElementAction | None = None

		result = await controller.act(
			ClickActionModel(click_element_by_index=ClickElementAction(index=block_index)), browser_session
		)

		assert result.error is None, f'Click failed: {result.error}'

		# Verify click worked
		cdp_session = await browser_session.get_or_create_cdp_session()
		result_js = await browser_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('result').textContent", 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		assert result_js.get('result', {}).get('value') == 'Block clicked'

	async def test_element_covered_by_overlay(self, controller, browser_session, base_url, http_server):
		"""Test clicking an element that's mostly covered by another element."""
		# Add route for overlapping elements
		http_server.expect_request('/covered_element').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Covered Element Test</title>
				<style>
					body { margin: 20px; position: relative; }
					.target {
						position: absolute;
						top: 50px;
						left: 50px;
						width: 200px;
						height: 100px;
						padding: 20px;
						background: #28a745;
						color: white;
						cursor: pointer;
						z-index: 1;
					}
					.overlay {
						position: absolute;
						top: 60px;
						left: 60px;
						width: 180px;
						height: 80px;
						background: rgba(255, 0, 0, 0.7);
						z-index: 2;
						pointer-events: none; /* Allow clicks through */
					}
					#result { margin-top: 200px; }
				</style>
			</head>
			<body>
				<div class="target" onclick="document.getElementById('result').textContent = 'Target clicked'">
					Click me (partially covered)
				</div>
				<div class="overlay">Overlaying element</div>
				<div id="result">Not clicked</div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to the page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/covered_element', new_tab=False)}

		from browser_use.agent.views import ActionModel

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)
		await asyncio.sleep(0.5)

		# Get the clickable elements
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)
		selector_map = await browser_session.get_selector_map()

		# Find the target element
		target_index = None
		for idx, element in selector_map.items():
			if 'target' in str(element.attributes.get('class', '')):
				target_index = idx
				break

		assert target_index is not None, 'Could not find target element'

		# Click should still work on the visible portion
		class ClickActionModel(ActionModel):
			click_element_by_index: ClickElementAction | None = None

		result = await controller.act(
			ClickActionModel(click_element_by_index=ClickElementAction(index=target_index)), browser_session
		)

		assert result.error is None, f'Click failed: {result.error}'

		# Verify click worked
		cdp_session = await browser_session.get_or_create_cdp_session()
		result_js = await browser_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('result').textContent", 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		assert result_js.get('result', {}).get('value') == 'Target clicked'

	async def test_file_input_click_prevention(self, controller, browser_session, base_url, http_server):
		"""Test that clicking a file input element raises an exception."""
		# Add route with file input
		http_server.expect_request('/file_input').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>File Input Test</title>
			</head>
			<body>
				<h1>File Upload Test</h1>
				<input type="file" id="fileInput" />
				<div id="result">No file selected</div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to the page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/file_input', new_tab=False)}

		from browser_use.agent.views import ActionModel

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)
		await asyncio.sleep(0.5)

		# Get the clickable elements
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)
		selector_map = await browser_session.get_selector_map()

		# Find the file input
		file_input_index = None
		for idx, element in selector_map.items():
			if element.tag_name and element.tag_name.lower() == 'input':
				if element.attributes and element.attributes.get('type') == 'file':
					file_input_index = idx
					break

		assert file_input_index is not None, 'Could not find file input element'

		# Attempt to click should raise an exception
		class ClickActionModel(ActionModel):
			click_element_by_index: ClickElementAction | None = None

		result = await controller.act(
			ClickActionModel(click_element_by_index=ClickElementAction(index=file_input_index)), browser_session
		)

		# Should have an error about file inputs
		assert result.error is not None, 'Expected error for file input click'
		assert 'file input' in result.error.lower() or 'file upload' in result.error.lower(), (
			f'Error message should mention file input, got: {result.error}'
		)

	async def test_select_dropdown_click_prevention(self, controller, browser_session, base_url, http_server):
		"""Test that clicking a select dropdown element raises an exception."""
		# Add route with select dropdown
		http_server.expect_request('/select_dropdown').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Select Dropdown Test</title>
			</head>
			<body>
				<h1>Select Test</h1>
				<select id="testSelect">
					<option value="">Choose one</option>
					<option value="opt1">Option 1</option>
					<option value="opt2">Option 2</option>
				</select>
				<div id="result">Nothing selected</div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to the page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/select_dropdown', new_tab=False)}

		from browser_use.agent.views import ActionModel

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action), browser_session)
		await asyncio.sleep(0.5)

		# Get the clickable elements
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)
		selector_map = await browser_session.get_selector_map()

		# Find the select element
		select_index = None
		for idx, element in selector_map.items():
			if element.tag_name and element.tag_name.lower() == 'select':
				select_index = idx
				break

		assert select_index is not None, 'Could not find select element'

		# Attempt to click should raise an exception
		class ClickActionModel(ActionModel):
			click_element_by_index: ClickElementAction | None = None

		result = await controller.act(
			ClickActionModel(click_element_by_index=ClickElementAction(index=select_index)), browser_session
		)

		# Should have an error about select elements
		assert result.error is not None, 'Expected error for select element click'
		assert 'select' in result.error.lower() and 'dropdown' in result.error.lower(), (
			f'Error message should mention select/dropdown, got: {result.error}'
		)

	async def test_click_triggers_alert_popup(self, browser_session, base_url, http_server):
		"""Test that clicking a button triggers an alert dialog that is auto-accepted."""
		from browser_use.browser.events import BrowserStateRequestEvent, ClickElementEvent, DialogOpenedEvent, NavigateToUrlEvent

		# Add route with alert dialog
		http_server.expect_request('/alert_test').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Alert Test</title>
			</head>
			<body>
				<h1>Alert Dialog Test</h1>
				<button id="alertButton" onclick="alert('This is an alert!'); document.getElementById('result').textContent = 'Alert shown';">
					Show Alert
				</button>
				<div id="result">No popup shown</div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to the alert test page using events
		nav_event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/alert_test'))
		await nav_event
		await asyncio.sleep(0.5)

		# Get the browser state to find clickable elements
		state_event = browser_session.event_bus.dispatch(BrowserStateRequestEvent())
		browser_state = await state_event.event_result(raise_if_none=True, raise_if_any=True)

		# Find the alert button
		alert_button = None
		for element in browser_state.dom_state.selector_map.values():
			if element.attributes and element.attributes.get('id') == 'alertButton':
				alert_button = element
				break

		assert alert_button is not None, 'Could not find alert button'

		# Expect the DialogOpenedEvent
		dialog_event_future = browser_session.event_bus.expect(DialogOpenedEvent)

		# Click the alert button using ClickElementEvent
		click_event = browser_session.event_bus.dispatch(ClickElementEvent(node=alert_button))
		await click_event

		# Wait for and verify DialogOpenedEvent was dispatched
		dialog_event = await asyncio.wait_for(dialog_event_future, timeout=2.0)
		assert dialog_event.dialog_type == 'alert'
		assert 'This is an alert!' in dialog_event.message

		# Verify the page updated after alert was accepted
		cdp_session = await browser_session.get_or_create_cdp_session()
		result_js = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('result').textContent", 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		assert result_js.get('result', {}).get('value') == 'Alert shown'

	async def test_click_triggers_confirm_popup(self, browser_session, base_url, http_server):
		"""Test that clicking a button triggers a confirm dialog that is auto-accepted."""
		from browser_use.browser.events import BrowserStateRequestEvent, ClickElementEvent, DialogOpenedEvent, NavigateToUrlEvent

		# Add route with confirm dialog
		http_server.expect_request('/confirm_test').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Confirm Test</title>
			</head>
			<body>
				<h1>Confirm Dialog Test</h1>
				<button id="confirmButton" onclick="if(confirm('Are you sure?')) { document.getElementById('result').textContent = 'Confirmed'; } else { document.getElementById('result').textContent = 'Cancelled'; }">
					Show Confirm
				</button>
				<div id="result">No popup shown</div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to the confirm test page
		nav_event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/confirm_test'))
		await nav_event
		await asyncio.sleep(0.5)

		# Get the browser state
		state_event = browser_session.event_bus.dispatch(BrowserStateRequestEvent())
		browser_state = await state_event.event_result(raise_if_none=True, raise_if_any=True)

		# Find the confirm button
		confirm_button = None
		for element in browser_state.dom_state.selector_map.values():
			if element.attributes and element.attributes.get('id') == 'confirmButton':
				confirm_button = element
				break

		assert confirm_button is not None, 'Could not find confirm button'

		# Expect the DialogOpenedEvent
		dialog_event_future = browser_session.event_bus.expect(DialogOpenedEvent)

		# Click the confirm button
		click_event = browser_session.event_bus.dispatch(ClickElementEvent(node=confirm_button))
		await click_event

		# Wait for and verify DialogOpenedEvent was dispatched
		dialog_event = await asyncio.wait_for(dialog_event_future, timeout=2.0)
		assert dialog_event.dialog_type == 'confirm'
		assert 'Are you sure?' in dialog_event.message

		# Verify the page updated after confirm was accepted (auto-accepts with True)
		cdp_session = await browser_session.get_or_create_cdp_session()
		result_js = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('result').textContent", 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		assert result_js.get('result', {}).get('value') == 'Confirmed'

	async def test_page_usable_after_popup_confirm(self, browser_session, base_url, http_server):
		"""Test that the page remains usable after handling confirm dialogs."""
		from browser_use.browser.events import BrowserStateRequestEvent, ClickElementEvent, DialogOpenedEvent, NavigateToUrlEvent

		# Add route with confirm dialog and navigation
		http_server.expect_request('/popup_nav_test').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Popup Navigation Test</title>
			</head>
			<body>
				<h1>Popup and Navigation Test</h1>
				<button id="confirmButton" onclick="if(confirm('Continue to navigation?')) { document.getElementById('result').textContent = 'Ready to navigate'; }">
					Show Confirm
				</button>
				<a href="/page1" id="navLink">Navigate to Page 1</a>
				<div id="result">No popup shown</div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to the test page
		nav_event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/popup_nav_test'))
		await nav_event
		await asyncio.sleep(0.5)

		# Get browser state
		state_event = browser_session.event_bus.dispatch(BrowserStateRequestEvent())
		browser_state = await state_event

		# Find and click the confirm button
		confirm_button = None
		for element in browser_state.dom_state.selector_map.values():
			if element.attributes and element.attributes.get('id') == 'confirmButton':
				confirm_button = element
				break

		assert confirm_button is not None, 'Could not find confirm button'

		# Expect dialog event
		dialog_event_future = browser_session.event_bus.expect(DialogOpenedEvent)

		# Click confirm button
		click_event = browser_session.event_bus.dispatch(ClickElementEvent(node=confirm_button))
		await click_event

		# Wait for dialog event
		dialog_event = await asyncio.wait_for(dialog_event_future, timeout=2.0)
		assert dialog_event.dialog_type == 'confirm'

		# Verify page was updated
		cdp_session = await browser_session.get_or_create_cdp_session()
		result_js = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('result').textContent", 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		assert result_js.get('result', {}).get('value') == 'Ready to navigate'

		# Refresh browser state after handling dialog
		state_event = browser_session.event_bus.dispatch(BrowserStateRequestEvent())
		browser_state = await state_event

		# Find and click navigation link to verify page is still usable
		nav_link = None
		for element in browser_state.dom_state.selector_map.values():
			if element.attributes and element.attributes.get('id') == 'navLink':
				nav_link = element
				break

		assert nav_link is not None, 'Could not find navigation link'

		# Click the navigation link
		click_event = browser_session.event_bus.dispatch(ClickElementEvent(node=nav_link))
		await click_event
		await asyncio.sleep(1)

		# Verify navigation succeeded
		current_url = await browser_session.get_current_page_url()
		assert f'{base_url}/page1' in current_url, f'Navigation failed, current URL: {current_url}'

		# Verify browser is still responsive
		current_title = await browser_session.get_current_page_title()
		assert 'Test Page 1' in current_title, f'Page title incorrect: {current_title}'

	async def test_click_triggers_onbeforeunload_popup(self, browser_session, base_url, http_server):
		"""Test that navigating away from a page with onbeforeunload triggers a dialog."""
		from browser_use.browser.events import BrowserStateRequestEvent, ClickElementEvent, DialogOpenedEvent, NavigateToUrlEvent

		# Add route with onbeforeunload handler
		http_server.expect_request('/beforeunload_test').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>BeforeUnload Test</title>
				<script>
					window.onbeforeunload = function(e) {
						e.preventDefault();
						e.returnValue = 'You have unsaved changes!';
						return 'You have unsaved changes!';
					};
				</script>
			</head>
			<body>
				<h1>BeforeUnload Test</h1>
				<p>This page has unsaved changes.</p>
				<a href="/page1" id="navLink">Navigate Away</a>
				<div id="result">Page loaded</div>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to the beforeunload test page
		nav_event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/beforeunload_test'))
		await nav_event
		await asyncio.sleep(0.5)

		# Get browser state
		state_event = browser_session.event_bus.dispatch(BrowserStateRequestEvent())
		browser_state = await state_event

		# Find the navigation link
		nav_link = None
		for element in browser_state.dom_state.selector_map.values():
			if element.attributes and element.attributes.get('id') == 'navLink':
				nav_link = element
				break

		assert nav_link is not None, 'Could not find navigation link'

		# Expect the DialogOpenedEvent for beforeunload
		dialog_event_future = browser_session.event_bus.expect(DialogOpenedEvent)

		# Click the navigation link - should trigger beforeunload popup
		click_event = browser_session.event_bus.dispatch(ClickElementEvent(node=nav_link))
		await click_event

		# Wait for and verify DialogOpenedEvent was dispatched
		dialog_event = await asyncio.wait_for(dialog_event_future, timeout=2.0)
		assert dialog_event.dialog_type == 'beforeunload'
		# Note: beforeunload messages are often browser-controlled and may not match our custom message

		# Wait a bit for navigation to complete after dialog is auto-accepted
		await asyncio.sleep(1)

		# Verify navigation succeeded after beforeunload was accepted
		current_url = await browser_session.get_current_page_url()
		assert f'{base_url}/page1' in current_url, (
			f'Navigation should have succeeded after beforeunload was accepted, current URL: {current_url}'
		)

	async def test_file_upload_click_and_verify(self, controller, browser_session, base_url, http_server):
		"""Test that clicking a file upload element and uploading a file works correctly."""
		# Create a temporary test file
		import tempfile as temp_module

		with temp_module.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as temp_file:
			temp_file.write('Test file content for upload')
			temp_file_path = temp_file.name

		try:
			# Add route for file upload test page
			http_server.expect_request('/fileupload').respond_with_data(
				"""
				<!DOCTYPE html>
				<html>
				<head>
					<title>File Upload Test</title>
					<style>
						.upload-section {
							margin: 20px;
							padding: 20px;
							border: 2px dashed #ccc;
						}
						#fileInfo {
							margin-top: 20px;
							padding: 10px;
							border: 1px solid #ddd;
							min-height: 50px;
						}
						.upload-label {
							display: inline-block;
							padding: 10px 20px;
							background-color: #4CAF50;
							color: white;
							cursor: pointer;
							border-radius: 4px;
						}
						.upload-label:hover {
							background-color: #45a049;
						}
						input[type="file"] {
							/* Hide the default file input */
							display: none;
						}
					</style>
				</head>
				<body>
					<h1>File Upload Test</h1>
					<div class="upload-section">
						<p>Click the button below to select a file:</p>
						<label for="fileInput" class="upload-label">Choose File</label>
						<input type="file" id="fileInput" name="fileInput" />
						<div id="fileInfo">
							<p id="fileName">No file selected</p>
							<p id="fileSize"></p>
							<p id="fileType"></p>
						</div>
					</div>
					
					<script>
						document.getElementById('fileInput').addEventListener('change', function(e) {
							const file = e.target.files[0];
							if (file) {
								document.getElementById('fileName').textContent = 'File name: ' + file.name;
								document.getElementById('fileSize').textContent = 'File size: ' + file.size + ' bytes';
								document.getElementById('fileType').textContent = 'File type: ' + (file.type || 'unknown');
							} else {
								document.getElementById('fileName').textContent = 'No file selected';
								document.getElementById('fileSize').textContent = '';
								document.getElementById('fileType').textContent = '';
							}
						});
					</script>
				</body>
				</html>
				""",
				content_type='text/html',
			)

			# Navigate to the file upload test page
			goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/fileupload', new_tab=False)}

			from browser_use.agent.views import ActionModel

			class GoToUrlActionModel(ActionModel):
				go_to_url: GoToUrlAction | None = None

			await controller.act(GoToUrlActionModel(**goto_action), browser_session)

			# Wait for the page to load
			await asyncio.sleep(0.5)

			# Initialize the DOM state to populate the selector map
			await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)

			# Get the selector map
			selector_map = await browser_session.get_selector_map()

			# Find the label element that triggers the file input
			label_index = None
			for idx, element in selector_map.items():
				if element.tag_name.lower() == 'label' and 'upload-label' in str(element.attributes.get('class', '')):
					label_index = idx
					break

			assert label_index is not None, 'Could not find file upload label element'

			# Create action model for file upload
			class UploadFileActionModel(ActionModel):
				upload_file_to_element: UploadFileAction | None = None

			# Create a temporary FileSystem for the test
			import tempfile

			from browser_use.filesystem.file_system import FileSystem

			with tempfile.TemporaryDirectory() as temp_dir:
				file_system = FileSystem(base_dir=temp_dir)

				# Upload the file using the label index (should find the associated file input)
				result = await controller.act(
					UploadFileActionModel(upload_file_to_element=UploadFileAction(index=label_index, path=temp_file_path)),
					browser_session,
					available_file_paths=[temp_file_path],  # Pass the file path as available
					file_system=file_system,  # Pass the required file_system parameter
				)

				# Verify the upload action succeeded
				assert result.error is None, f'File upload failed: {result.error}'
				assert result.extracted_content is not None
				assert 'Successfully uploaded file' in result.extracted_content

				# Wait a moment for the JavaScript to process the file
				await asyncio.sleep(0.5)

				# Verify the file was actually selected using CDP Runtime.evaluate
				cdp_session = await browser_session.get_or_create_cdp_session()

				# Check if the file input has a file selected
				file_check_js = await browser_session.cdp_client.send.Runtime.evaluate(
					params={
						'expression': """
							(() => {
								const input = document.getElementById('fileInput');
								if (!input || !input.files || input.files.length === 0) {
									return { hasFile: false };
								}
								const file = input.files[0];
								return {
									hasFile: true,
									fileName: file.name,
									fileSize: file.size,
									fileType: file.type || 'text/plain'
								};
							})()
						""",
						'returnByValue': True,
					},
					session_id=cdp_session.session_id,
				)

				file_info = file_check_js.get('result', {}).get('value', {})

				# Verify file was selected
				assert file_info.get('hasFile') is True, 'File was not properly selected in the input element'
				assert file_info.get('fileName', '').endswith('.txt'), f'Expected .txt file, got: {file_info.get("fileName")}'
				assert file_info.get('fileSize', 0) > 0, 'File size should be greater than 0'

				# Also verify the UI was updated (the file info div)
				ui_check_js = await browser_session.cdp_client.send.Runtime.evaluate(
					params={
						'expression': """
							(() => {
								const fileName = document.getElementById('fileName').textContent;
								const fileSize = document.getElementById('fileSize').textContent;
								return {
									fileNameText: fileName,
									fileSizeText: fileSize,
									hasFileInfo: !fileName.includes('No file selected')
								};
							})()
						""",
						'returnByValue': True,
					},
					session_id=cdp_session.session_id,
				)

				ui_info = ui_check_js.get('result', {}).get('value', {})

				# Verify UI was updated
				assert ui_info.get('hasFileInfo') is True, 'UI was not updated with file information'
				assert '.txt' in ui_info.get('fileNameText', ''), f'File name not shown in UI: {ui_info.get("fileNameText")}'
				assert 'bytes' in ui_info.get('fileSizeText', ''), f'File size not shown in UI: {ui_info.get("fileSizeText")}'

		finally:
			# Clean up the temporary file
			Path(temp_file_path).unlink(missing_ok=True)

	async def test_file_upload_path_validation(self, controller, browser_session, base_url, http_server):
		"""Test that file upload validates paths correctly with available_file_paths, downloaded_files, and FileSystem."""
		from pathlib import Path

		from browser_use.browser.views import BrowserError
		from browser_use.controller.views import UploadFileAction
		from browser_use.filesystem.file_system import FileSystem

		# Create a temporary test file that's NOT in available_file_paths
		with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as temp_file:
			temp_file.write('Test file content')
			test_file_path = temp_file.name

		try:
			# Set up test page with file input
			http_server.expect_request('/upload-test').respond_with_data(
				"""
				<html>
				<body>
					<h1>File Upload Test</h1>
					<input type="file" id="fileInput" />
				</body>
				</html>
				""",
				content_type='text/html',
			)

			# Navigate to the test page
			goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/upload-test', new_tab=False)}
			from browser_use.agent.views import ActionModel

			class GoToUrlActionModel(ActionModel):
				go_to_url: GoToUrlAction | None = None

			await controller.act(GoToUrlActionModel(**goto_action), browser_session)
			await asyncio.sleep(0.5)

			# Get browser state to populate selector map
			from browser_use.browser.events import BrowserStateRequestEvent

			event = browser_session.event_bus.dispatch(BrowserStateRequestEvent())
			state = await event

			# Test 1: Try to upload a file that's not in available_file_paths - should fail
			class UploadActionModel(ActionModel):
				upload_file_to_element: UploadFileAction | None = None

			upload_action = UploadActionModel(upload_file_to_element=UploadFileAction(index=1, path=test_file_path))

			# Create a temporary FileSystem for all tests
			with tempfile.TemporaryDirectory() as temp_dir:
				file_system = FileSystem(base_dir=temp_dir)

				try:
					# This should fail because the file is not in available_file_paths
					result = await controller.act(
						upload_action,
						browser_session,
						available_file_paths=[],  # Empty available_file_paths
						file_system=file_system,
					)
					assert result.error is not None, 'Upload should have failed for file not in available_file_paths'
					assert 'not available' in result.error, f'Error message should mention file not available: {result.error}'
				except BrowserError as e:
					assert 'not available' in str(e), f'Error should mention file not available: {e}'

				# Test 2: Add file to available_file_paths - should succeed
				result = await controller.act(
					upload_action,
					browser_session,
					available_file_paths=[test_file_path],  # File is now in available_file_paths
					file_system=file_system,
				)
				assert result.error is None, f'Upload should have succeeded with file in available_file_paths: {result.error}'

				# Test 3: Test with FileSystem integration - write a test file to the FileSystem
				await file_system.write_file('test.txt', 'FileSystem test content')
				fs_file_path = str(file_system.get_dir() / 'test.txt')

				# Try to upload using just the filename (should check FileSystem)
				upload_action_fs = UploadActionModel(upload_file_to_element=UploadFileAction(index=1, path='test.txt'))

				result = await controller.act(
					upload_action_fs,
					browser_session,
					available_file_paths=[],  # Empty available_file_paths
					file_system=file_system,  # But FileSystem is provided
				)
				assert result.error is None, f'Upload should have succeeded with file in FileSystem: {result.error}'

				# Test 4: Simulate a downloaded file
				# Manually add a file to browser_session._downloaded_files to simulate a download
				browser_session._downloaded_files.append(test_file_path)

				# Try uploading with the file only in downloaded_files
				result = await controller.act(
					upload_action,
					browser_session,
					available_file_paths=[],  # Empty available_file_paths, but file is in downloaded_files
					file_system=file_system,
				)
				assert result.error is None, f'Upload should have succeeded with file in downloaded_files: {result.error}'

		finally:
			# Clean up the temporary file
			Path(test_file_path).unlink(missing_ok=True)
