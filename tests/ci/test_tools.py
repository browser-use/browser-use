import asyncio
import tempfile
import time

import pytest
from pydantic import BaseModel
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.filesystem.file_system import FileSystem
from browser_use.tools.service import Tools
from browser_use.tools.views import (
	DoneAction,
	GoToUrlAction,
	NoParamsAction,
	SearchGoogleAction,
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
def tools():
	"""Create and provide a Tools instance."""
	return Tools()


class TestToolsIntegration:
	"""Integration tests for Tools using actual browser instances."""

	async def test_registry_actions(self, tools, browser_session):
		"""Test that the registry contains the expected default actions."""
		# Check that common actions are registered
		common_actions = [
			'go_to_url',
			'search_google',
			'click_element_by_index',
			'input_text',
			'scroll',
			'go_back',
			'switch_tab',
			'close_tab',
			'wait',
		]

		for action in common_actions:
			assert action in tools.registry.registry.actions
			assert tools.registry.registry.actions[action].function is not None
			assert tools.registry.registry.actions[action].description is not None

	async def test_custom_action_registration(self, tools, browser_session, base_url):
		"""Test registering a custom action and executing it."""

		# Define a custom action
		class CustomParams(BaseModel):
			text: str

		@tools.action('Test custom action', param_model=CustomParams)
		async def custom_action(params: CustomParams, browser_session):
			current_url = await browser_session.get_current_page_url()
			return ActionResult(extracted_content=f'Custom action executed with: {params.text} on {current_url}')

		# Navigate to a page first
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/page1', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await tools.act(GoToUrlActionModel(**goto_action), browser_session)

		# Create the custom action model
		custom_action_data = {'custom_action': CustomParams(text='test_value')}

		class CustomActionModel(ActionModel):
			custom_action: CustomParams | None = None

		# Execute the custom action
		result = await tools.act(CustomActionModel(**custom_action_data), browser_session)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Custom action executed with: test_value on' in result.extracted_content
		assert f'{base_url}/page1' in result.extracted_content

	async def test_wait_action(self, tools, browser_session):
		"""Test that the wait action correctly waits for the specified duration."""

		# verify that it's in the default action set
		wait_action = None
		for action_name, action in tools.registry.registry.actions.items():
			if 'wait' in action_name.lower() and 'seconds' in str(action.param_model.model_fields):
				wait_action = action
				break
		assert wait_action is not None, 'Could not find wait action in tools'

		# Check that it has seconds parameter with default
		assert 'seconds' in wait_action.param_model.model_fields
		schema = wait_action.param_model.model_json_schema()
		assert schema['properties']['seconds']['default'] == 3

		# Create wait action for 1 second - fix to use a dictionary
		wait_action = {'wait': {'seconds': 1}}  # Corrected format

		class WaitActionModel(ActionModel):
			wait: dict | None = None

		# Record start time
		start_time = time.time()

		# Execute wait action
		result = await tools.act(WaitActionModel(**wait_action), browser_session)

		# Record end time
		end_time = time.time()

		# Verify the result
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Waited for' in result.extracted_content or 'Waiting for' in result.extracted_content

		# Verify that approximately 1 second has passed (allowing some margin)
		assert 0.8 <= end_time - start_time <= 1.5  # Allow some timing margin for 1 second wait

		# longer wait
		# Create wait action for 1 second - fix to use a dictionary
		wait_action = {'wait': {'seconds': 5}}  # Corrected format

		# Record start time
		start_time = time.time()

		# Execute wait action
		result = await tools.act(WaitActionModel(**wait_action), browser_session)

		# Record end time
		end_time = time.time()

		# Verify the result
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Waited for' in result.extracted_content or 'Waiting for' in result.extracted_content

		# Verify that approximately 5 seconds have passed (allowing some margin)
		assert 4.5 <= end_time - start_time <= 6.0  # Allow some timing margin for 5 second wait
		assert end_time - start_time >= 1.9  # Allow some timing margin

	async def test_go_back_action(self, tools, browser_session, base_url):
		"""Test that go_back action navigates to the previous page."""
		# Navigate to first page
		goto_action1 = {'go_to_url': GoToUrlAction(url=f'{base_url}/page1', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await tools.act(GoToUrlActionModel(**goto_action1), browser_session)

		# Store the first page URL
		first_url = await browser_session.get_current_page_url()
		print(f'First page URL: {first_url}')

		# Navigate to second page
		goto_action2 = {'go_to_url': GoToUrlAction(url=f'{base_url}/page2', new_tab=False)}
		await tools.act(GoToUrlActionModel(**goto_action2), browser_session)

		# Verify we're on the second page
		second_url = await browser_session.get_current_page_url()
		print(f'Second page URL: {second_url}')
		assert f'{base_url}/page2' in second_url

		# Execute go back action
		go_back_action = {'go_back': NoParamsAction()}

		class GoBackActionModel(ActionModel):
			go_back: NoParamsAction | None = None

		result = await tools.act(GoBackActionModel(**go_back_action), browser_session)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Navigated back' in result.extracted_content

		# Add another delay to allow the navigation to complete
		await asyncio.sleep(1)

		# Verify we're back on a different page than before
		final_url = await browser_session.get_current_page_url()
		print(f'Final page URL after going back: {final_url}')

		# Try to verify we're back on the first page, but don't fail the test if not
		assert f'{base_url}/page1' in final_url, f'Expected to return to page1 but got {final_url}'

	async def test_navigation_chain(self, tools, browser_session, base_url):
		"""Test navigating through multiple pages and back through history."""
		# Set up a chain of navigation: Home -> Page1 -> Page2
		urls = [f'{base_url}/', f'{base_url}/page1', f'{base_url}/page2']

		# Navigate to each page in sequence
		for url in urls:
			action_data = {'go_to_url': GoToUrlAction(url=url, new_tab=False)}

			class GoToUrlActionModel(ActionModel):
				go_to_url: GoToUrlAction | None = None

			await tools.act(GoToUrlActionModel(**action_data), browser_session)

			# Verify current page
			current_url = await browser_session.get_current_page_url()
			assert url in current_url

		# Go back twice and verify each step
		for expected_url in reversed(urls[:-1]):
			go_back_action = {'go_back': NoParamsAction()}

			class GoBackActionModel(ActionModel):
				go_back: NoParamsAction | None = None

			await tools.act(GoBackActionModel(**go_back_action), browser_session)
			await asyncio.sleep(1)  # Wait for navigation to complete

			current_url = await browser_session.get_current_page_url()
			assert expected_url in current_url

	async def test_excluded_actions(self, browser_session):
		"""Test that excluded actions are not registered."""
		# Create tools with excluded actions
		excluded_tools = Tools(exclude_actions=['search_google', 'scroll'])

		# Verify excluded actions are not in the registry
		assert 'search_google' not in excluded_tools.registry.registry.actions
		assert 'scroll' not in excluded_tools.registry.registry.actions

		# But other actions are still there
		assert 'go_to_url' in excluded_tools.registry.registry.actions
		assert 'click_element_by_index' in excluded_tools.registry.registry.actions

	async def test_search_google_action(self, tools, browser_session, base_url):
		"""Test the search_google action."""

		await browser_session.get_current_page_url()

		# Execute search_google action - it will actually navigate to our search results page
		search_action = {'search_google': SearchGoogleAction(query='Python web automation')}

		class SearchGoogleActionModel(ActionModel):
			search_google: SearchGoogleAction | None = None

		result = await tools.act(SearchGoogleActionModel(**search_action), browser_session)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Searched' in result.extracted_content and 'Python web automation' in result.extracted_content

		# For our test purposes, we just verify we're on some URL
		current_url = await browser_session.get_current_page_url()
		assert current_url is not None and 'Python' in current_url

	async def test_done_action(self, tools, browser_session, base_url):
		"""Test that DoneAction completes a task and reports success or failure."""
		# Create a temporary directory for the file system
		with tempfile.TemporaryDirectory() as temp_dir:
			file_system = FileSystem(temp_dir)

			# First navigate to a page
			goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/page1', new_tab=False)}

			class GoToUrlActionModel(ActionModel):
				go_to_url: GoToUrlAction | None = None

			await tools.act(GoToUrlActionModel(**goto_action), browser_session)

			success_done_message = 'Successfully completed task'

			# Create done action with success
			done_action = {'done': DoneAction(text=success_done_message, success=True)}

			class DoneActionModel(ActionModel):
				done: DoneAction | None = None

			# Execute done action with file_system
			result = await tools.act(DoneActionModel(**done_action), browser_session, file_system=file_system)

			# Verify the result
			assert isinstance(result, ActionResult)
			assert result.extracted_content is not None
			assert success_done_message in result.extracted_content
			assert result.success is True
			assert result.is_done is True
			assert result.error is None

			failed_done_message = 'Failed to complete task'

			# Test with failure case
			failed_done_action = {'done': DoneAction(text=failed_done_message, success=False)}

			# Execute failed done action with file_system
			result = await tools.act(DoneActionModel(**failed_done_action), browser_session, file_system=file_system)

			# Verify the result
			assert isinstance(result, ActionResult)
			assert result.extracted_content is not None
			assert failed_done_message in result.extracted_content
			assert result.success is False
			assert result.is_done is True
			assert result.error is None

	async def test_get_dropdown_options(self, tools, browser_session, base_url, http_server):
		"""Test that get_dropdown_options correctly retrieves options from a dropdown."""
		# Add route for dropdown test page
		http_server.expect_request('/dropdown1').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Dropdown Test</title>
			</head>
			<body>
				<h1>Dropdown Test</h1>
				<select id="test-dropdown" name="test-dropdown">
					<option value="">Please select</option>
					<option value="option1">First Option</option>
					<option value="option2">Second Option</option>
					<option value="option3">Third Option</option>
				</select>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to the dropdown test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/dropdown1', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await tools.act(GoToUrlActionModel(**goto_action), browser_session)

		# Wait for the page to load using CDP
		cdp_session = browser_session.agent_focus
		assert cdp_session is not None, 'CDP session not initialized'

		# Wait for page load by checking document ready state
		await asyncio.sleep(0.5)  # Brief wait for navigation to start
		ready_state = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'document.readyState'}, session_id=cdp_session.session_id
		)
		# If not complete, wait a bit more
		if ready_state.get('result', {}).get('value') != 'complete':
			await asyncio.sleep(1.0)

		# Initialize the DOM state to populate the selector map
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)

		# Get the selector map
		selector_map = await browser_session.get_selector_map()

		# Find the dropdown element in the selector map
		dropdown_index = None
		for idx, element in selector_map.items():
			if element.tag_name.lower() == 'select':
				dropdown_index = idx
				break

		assert dropdown_index is not None, (
			f'Could not find select element in selector map. Available elements: {[f"{idx}: {element.tag_name}" for idx, element in selector_map.items()]}'
		)

		# Create a model for the standard get_dropdown_options action
		class GetDropdownOptionsModel(ActionModel):
			get_dropdown_options: dict[str, int]

		# Execute the action with the dropdown index
		result = await tools.act(
			action=GetDropdownOptionsModel(get_dropdown_options={'index': dropdown_index}),
			browser_session=browser_session,
		)

		expected_options = [
			{'index': 0, 'text': 'Please select', 'value': ''},
			{'index': 1, 'text': 'First Option', 'value': 'option1'},
			{'index': 2, 'text': 'Second Option', 'value': 'option2'},
			{'index': 3, 'text': 'Third Option', 'value': 'option3'},
		]

		# Verify the result structure
		assert isinstance(result, ActionResult)

		# Core logic validation: Verify all options are returned
		assert result.extracted_content is not None
		for option in expected_options[1:]:  # Skip the placeholder option
			assert option['text'] in result.extracted_content, f"Option '{option['text']}' not found in result content"

		# Verify the instruction for using the text in select_dropdown_option is included
		assert (
			'Use the exact text or value string' in result.extracted_content
			and 'select_dropdown_option' in result.extracted_content
		)

		# Verify the actual dropdown options in the DOM using CDP
		dropdown_options_result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': """
					JSON.stringify((() => {
						const select = document.getElementById('test-dropdown');
						return Array.from(select.options).map(opt => ({
							text: opt.text,
							value: opt.value
						}));
					})())
				""",
				'returnByValue': True,
			},
			session_id=cdp_session.session_id,
		)
		dropdown_options_json = dropdown_options_result.get('result', {}).get('value', '[]')
		import json

		dropdown_options = json.loads(dropdown_options_json) if isinstance(dropdown_options_json, str) else dropdown_options_json

		# Verify the dropdown has the expected options
		assert len(dropdown_options) == len(expected_options), (
			f'Expected {len(expected_options)} options, got {len(dropdown_options)}'
		)
		for i, expected in enumerate(expected_options):
			actual = dropdown_options[i]
			assert actual['text'] == expected['text'], (
				f"Option at index {i} has wrong text: expected '{expected['text']}', got '{actual['text']}'"
			)
			assert actual['value'] == expected['value'], (
				f"Option at index {i} has wrong value: expected '{expected['value']}', got '{actual['value']}'"
			)

	async def test_select_dropdown_option(self, tools, browser_session, base_url, http_server):
		"""Test that select_dropdown_option correctly selects an option from a dropdown."""
		# Add route for dropdown test page
		http_server.expect_request('/dropdown2').respond_with_data(
			"""
			<!DOCTYPE html>
			<html>
			<head>
				<title>Dropdown Test</title>
			</head>
			<body>
				<h1>Dropdown Test</h1>
				<select id="test-dropdown" name="test-dropdown">
					<option value="">Please select</option>
					<option value="option1">First Option</option>
					<option value="option2">Second Option</option>
					<option value="option3">Third Option</option>
				</select>
			</body>
			</html>
			""",
			content_type='text/html',
		)

		# Navigate to the dropdown test page
		goto_action = {'go_to_url': GoToUrlAction(url=f'{base_url}/dropdown2', new_tab=False)}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await tools.act(GoToUrlActionModel(**goto_action), browser_session)

		# Wait for the page to load using CDP
		cdp_session = browser_session.agent_focus
		assert cdp_session is not None, 'CDP session not initialized'

		# Wait for page load by checking document ready state
		await asyncio.sleep(0.5)  # Brief wait for navigation to start
		ready_state = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'document.readyState'}, session_id=cdp_session.session_id
		)
		# If not complete, wait a bit more
		if ready_state.get('result', {}).get('value') != 'complete':
			await asyncio.sleep(1.0)

		# populate the selector map with highlight indices
		await browser_session.get_browser_state_summary(cache_clickable_elements_hashes=True)

		# Now get the selector map which should contain our dropdown
		selector_map = await browser_session.get_selector_map()

		# Find the dropdown element in the selector map
		dropdown_index = None
		for idx, element in selector_map.items():
			if element.tag_name.lower() == 'select':
				dropdown_index = idx
				break

		assert dropdown_index is not None, (
			f'Could not find select element in selector map. Available elements: {[f"{idx}: {element.tag_name}" for idx, element in selector_map.items()]}'
		)

		# Create a model for the standard select_dropdown_option action
		class SelectDropdownOptionModel(ActionModel):
			select_dropdown_option: dict

		# Execute the action with the dropdown index
		result = await tools.act(
			SelectDropdownOptionModel(select_dropdown_option={'index': dropdown_index, 'text': 'Second Option'}),
			browser_session,
		)

		# Verify the result structure
		assert isinstance(result, ActionResult)

		# Core logic validation: Verify selection was successful
		assert result.extracted_content is not None
		assert 'selected option' in result.extracted_content.lower()
		assert 'Second Option' in result.extracted_content

		# Verify the actual dropdown selection was made by checking the DOM using CDP
		selected_value_result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': "document.getElementById('test-dropdown').value"}, session_id=cdp_session.session_id
		)
		selected_value = selected_value_result.get('result', {}).get('value')
		assert selected_value == 'option2'  # Second Option has value "option2"
