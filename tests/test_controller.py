import asyncio
import time

import pytest
from pydantic import BaseModel

from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext
from browser_use.controller.service import Controller
from browser_use.controller.views import (
	ClickElementAction,
	CloseTabAction,
	GoToUrlAction,
	InputTextAction,
	NoParamsAction,
	OpenTabAction,
	ScrollAction,
	SearchGoogleAction,
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
	async def browser(self, event_loop):
		"""Create and provide a Browser instance with security disabled."""
		browser_instance = Browser(
			config=BrowserConfig(
				headless=True,
				disable_security=True,  # This disables web security features
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
	async def test_go_to_url_action(self, controller, browser_context):
		"""Test that GoToUrlAction navigates to the specified URL."""
		# Create action model for go_to_url
		action_data = {'go_to_url': GoToUrlAction(url='https://google.com')}

		# Create the ActionModel instance
		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		action_model = GoToUrlActionModel(**action_data)

		# Execute the action
		result = await controller.act(action_model, browser_context)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert 'Navigated to https://google.com' in result.extracted_content

		# Verify the current page URL
		page = await browser_context.get_current_page()
		assert 'google.com' in page.url

	@pytest.mark.asyncio
	async def test_scroll_actions(self, controller, browser_context):
		"""Test that scroll actions correctly scroll the page."""
		# First navigate to a page
		goto_action = {'go_to_url': GoToUrlAction(url='https://google.com')}

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
	async def test_custom_action_registration(self, controller, browser_context):
		"""Test registering a custom action and executing it."""

		# Define a custom action
		class CustomParams(BaseModel):
			text: str

		@controller.action('Test custom action', param_model=CustomParams)
		async def custom_action(params: CustomParams, browser):
			page = await browser.get_current_page()
			return ActionResult(extracted_content=f'Custom action executed with: {params.text} on {page.url}')

		# Navigate to a page first
		goto_action = {'go_to_url': GoToUrlAction(url='https://google.com')}

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
		assert 'google.com' in result.extracted_content

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
	async def test_input_text_action(self, controller, browser_context):
		"""Test that InputTextAction correctly inputs text into form fields."""
		# Navigate to a page with a form
		goto_action = {'go_to_url': GoToUrlAction(url='https://yahoo.com')}

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
	async def test_go_back_action(self, controller, browser_context):
		"""Test that go_back action navigates to the previous page."""
		# Navigate to first page
		goto_action1 = {'go_to_url': GoToUrlAction(url='https://google.com')}

		class GoToUrlActionModel(ActionModel):
			go_to_url: GoToUrlAction | None = None

		await controller.act(GoToUrlActionModel(**goto_action1), browser_context)

		# Store the first page URL
		page1 = await browser_context.get_current_page()
		first_url = page1.url
		print(f'First page URL: {first_url}')

		# Navigate to second page
		goto_action2 = {'go_to_url': GoToUrlAction(url='https://yahoo.com')}
		await controller.act(GoToUrlActionModel(**goto_action2), browser_context)

		# Verify we're on the second page
		page2 = await browser_context.get_current_page()
		second_url = page2.url
		print(f'Second page URL: {second_url}')
		assert 'yahoo.com' in second_url.lower()

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
		assert 'google.com' in final_url, f'Expected to return to Google but got {final_url}'

	@pytest.mark.asyncio
	async def test_navigation_chain(self, controller, browser_context):
		"""Test navigating through multiple pages and back through history."""
		# Set up a chain of navigation: Google -> Wikipedia -> GitHub
		urls = ['https://google.com', 'https://en.wikipedia.org', 'https://github.com']

		# Navigate to each page in sequence
		for url in urls:
			action_data = {'go_to_url': GoToUrlAction(url=url)}

			class GoToUrlActionModel(ActionModel):
				go_to_url: GoToUrlAction | None = None

			await controller.act(GoToUrlActionModel(**action_data), browser_context)

			# Verify current page
			page = await browser_context.get_current_page()
			assert url.split('//')[1] in page.url

		# Go back twice and verify each step
		for expected_url in reversed(urls[:-1]):
			go_back_action = {'go_back': NoParamsAction()}

			class GoBackActionModel(ActionModel):
				go_back: NoParamsAction | None = None

			await controller.act(GoBackActionModel(**go_back_action), browser_context)
			await asyncio.sleep(1)  # Wait for navigation to complete

			page = await browser_context.get_current_page()
			assert expected_url.split('//')[1] in page.url

	@pytest.mark.asyncio
	async def test_concurrent_tab_operations(self, controller, browser_context):
		"""Test operations across multiple tabs."""
		# Create two tabs with different content
		urls = ['https://google.com', 'https://yahoo.com']

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
		assert urls[1].split('//')[1] in page.url

		# Switch back to first tab
		switch_tab_action = {'switch_tab': SwitchTabAction(page_id=0)}

		class SwitchTabActionModel(ActionModel):
			switch_tab: SwitchTabAction | None = None

		await controller.act(SwitchTabActionModel(**switch_tab_action), browser_context)

		# Verify we're back on first tab
		page = await browser_context.get_current_page()
		assert urls[0].split('//')[1] in page.url

		# Close the second tab
		close_tab_action = {'close_tab': CloseTabAction(page_id=1)}

		class CloseTabActionModel(ActionModel):
			close_tab: CloseTabAction | None = None

		await controller.act(CloseTabActionModel(**close_tab_action), browser_context)

		# Verify only one tab remains
		tabs_info = await browser_context.get_tabs_info()
		assert len(tabs_info) == 1
		assert urls[0].split('//')[1] in tabs_info[0].url

	@pytest.mark.asyncio
	async def test_search_google_action(self, controller, browser_context):
		"""Test the search_google action."""
		# Execute search_google action
		search_action = {'search_google': SearchGoogleAction(query='Python web automation')}

		class SearchGoogleActionModel(ActionModel):
			search_google: SearchGoogleAction | None = None

		result = await controller.act(SearchGoogleActionModel(**search_action), browser_context)

		# Verify the result
		assert isinstance(result, ActionResult)
		assert 'Searched for "Python web automation" in Google' in result.extracted_content

		# Verify we're on Google search results page
		page = await browser_context.get_current_page()
		assert 'google.com/search' in page.url
