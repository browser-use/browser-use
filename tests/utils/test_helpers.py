"""Test helper utilities for browser-use tests.

This module provides common utilities, fixtures, and helper functions
for testing the browser-use library.
"""

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from browser_use.agent.views import ActionResult, AgentHistory, AgentOutput
from browser_use.browser.views import BrowserState


class MockLLM:
	"""Mock LLM for deterministic testing."""

	def __init__(self, responses: List[str] | None = None):
		"""Initialize with predefined responses.

		Args:
		    responses: List of responses to return in order
		"""
		self.responses = responses or []
		self.call_count = 0
		self.messages_received: List[Any] = []

	async def ainvoke(self, messages: List[Any], **kwargs) -> AIMessage:
		"""Mock async invoke that returns predefined responses.

		Args:
		    messages: Messages to process
		    **kwargs: Additional arguments

		Returns:
		    AIMessage with predefined content
		"""
		self.messages_received.append(messages)
		if self.call_count < len(self.responses):
			response = self.responses[self.call_count]
		else:
			response = 'Default response'

		self.call_count += 1
		return AIMessage(content=response)

	def reset(self):
		"""Reset the mock state."""
		self.call_count = 0
		self.messages_received = []


class MockBrowserState:
	"""Mock browser state for testing."""

	@staticmethod
	def create(
		url: str = 'https://example.com',
		title: str = 'Example Page',
		tabs: List[Dict[str, Any]] | None = None,
		selector_map: Dict[int, Any] | None = None,
	) -> BrowserState:
		"""Create a mock browser state.

		Args:
		    url: Current URL
		    title: Page title
		    tabs: List of open tabs
		    selector_map: Map of element indices to selectors

		Returns:
		    BrowserState instance for testing
		"""
		return BrowserState(
			url=url,
			title=title,
			tabs=tabs or [{'url': url, 'title': title}],
			selector_map=selector_map or {},
			element_tree=[],
			screenshot='',
		)


class MockActionResult:
	"""Factory for creating mock action results."""

	@staticmethod
	def success(
		content: str = 'Action completed successfully', include_in_memory: bool = True, is_done: bool = False
	) -> ActionResult:
		"""Create a successful action result.

		Args:
		    content: Result content
		    include_in_memory: Whether to include in agent memory
		    is_done: Whether the task is complete

		Returns:
		    ActionResult instance
		"""
		return ActionResult(extracted_content=content, include_in_memory=include_in_memory, is_done=is_done)

	@staticmethod
	def error(error_message: str = 'Action failed') -> ActionResult:
		"""Create an error action result.

		Args:
		    error_message: Error description

		Returns:
		    ActionResult instance with error
		"""
		return ActionResult(error=error_message, include_in_memory=True)

	@staticmethod
	def done(content: str = 'Task completed') -> ActionResult:
		"""Create a completion action result.

		Args:
		    content: Final result content

		Returns:
		    ActionResult marking task as done
		"""
		return ActionResult(extracted_content=content, is_done=True, include_in_memory=True)


class TestDataBuilder:
	"""Builder pattern for creating complex test data."""

	@staticmethod
	def build_agent_history(
		steps: int = 3, success: bool = True, final_result: Optional[str] = None
	) -> List[AgentHistory]:
		"""Build a list of agent history entries.

		Args:
		    steps: Number of steps to create
		    success: Whether actions were successful
		    final_result: Final result if task completed

		Returns:
		    List of AgentHistory entries
		"""
		history = []
		for i in range(steps):
			is_last = i == steps - 1
			result = MockActionResult.done(final_result) if is_last and final_result else MockActionResult.success()

			history.append(
				AgentHistory(
					model_output=AgentOutput(
						current_state=MockBrowserState.create(), action=[{'go_to_url': {'url': f'https://test{i}.com'}}]
					),
					result=[result],
					state=MockBrowserState.create(url=f'https://test{i}.com'),
				)
			)
		return history


async def wait_for_condition(
	condition_fn: callable, timeout: float = 5.0, interval: float = 0.1, error_msg: str = 'Condition not met'
):
	"""Wait for a condition to be true with timeout.

	Args:
	    condition_fn: Function that returns True when condition is met
	    timeout: Maximum time to wait in seconds
	    interval: Time between checks in seconds
	    error_msg: Error message if timeout occurs

	Raises:
	    TimeoutError: If condition not met within timeout
	"""
	elapsed = 0.0
	while elapsed < timeout:
		if await condition_fn() if asyncio.iscoroutinefunction(condition_fn) else condition_fn():
			return
		await asyncio.sleep(interval)
		elapsed += interval
	raise TimeoutError(f'{error_msg} (timeout after {timeout}s)')


def assert_action_type(action: Dict[str, Any], expected_type: str):
	"""Assert that an action is of the expected type.

	Args:
	    action: Action dictionary
	    expected_type: Expected action type (e.g., 'click_element')

	Raises:
	    AssertionError: If action type doesn't match
	"""
	assert expected_type in action, f'Expected action type {expected_type}, got {list(action.keys())}'


def assert_action_params(action: Dict[str, Any], action_type: str, expected_params: Dict[str, Any]):
	"""Assert that action parameters match expected values.

	Args:
	    action: Action dictionary
	    action_type: Type of action (e.g., 'click_element')
	    expected_params: Expected parameter values

	Raises:
	    AssertionError: If parameters don't match
	"""
	assert_action_type(action, action_type)
	actual_params = action[action_type]
	for key, expected_value in expected_params.items():
		assert key in actual_params, f'Parameter {key} not found in action'
		assert actual_params[key] == expected_value, f'Expected {key}={expected_value}, got {actual_params[key]}'


class MockBrowser:
	"""Mock browser for testing without actual browser automation."""

	def __init__(self):
		self.pages: List[MagicMock] = [self._create_mock_page()]
		self.current_page_index = 0
		self.closed = False

	def _create_mock_page(self) -> MagicMock:
		"""Create a mock page object."""
		page = MagicMock()
		page.goto = AsyncMock()
		page.click = AsyncMock()
		page.fill = AsyncMock()
		page.type = AsyncMock()
		page.screenshot = AsyncMock(return_value=b'mock_screenshot')
		page.content = AsyncMock(return_value='<html><body>Mock content</body></html>')
		page.url = 'https://example.com'
		page.title = AsyncMock(return_value='Mock Page')
		return page

	async def get_current_page(self):
		"""Get the current page."""
		return self.pages[self.current_page_index]

	async def new_page(self):
		"""Create a new page."""
		page = self._create_mock_page()
		self.pages.append(page)
		return page

	async def close(self):
		"""Close the browser."""
		self.closed = True


def create_mock_element(index: int, tag: str = 'button', text: str = 'Click me', **attributes) -> Dict[str, Any]:
	"""Create a mock DOM element.

	Args:
	    index: Element index in selector map
	    tag: HTML tag name
	    text: Element text content
	    **attributes: Additional element attributes

	Returns:
	    Dictionary representing a DOM element
	"""
	element = {
		'id': index,
		'tagName': tag,
		'text': text,
		'attributes': attributes,
	}
	return element
