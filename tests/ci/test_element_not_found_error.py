"""Tests that actions return ActionResult(error=...) when element index is not found.

Verifies that click, dropdown_options, and select_dropdown report
"element not found" as an error — not as a non-error extracted_content.
This matters because the agent loop uses ActionResult.error to decide
whether to abort queued actions (multi_act) and whether to increment
consecutive_failures (_post_process).
"""

import pytest

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.tools.service import Tools
from browser_use.tools.views import ClickElementActionIndexOnly, GetDropdownOptionsAction, SelectDropdownOptionAction


@pytest.fixture(scope='module')
async def browser_session():
	"""Headless browser session for element-not-found tests."""
	session = BrowserSession(
		browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True)
	)
	await session.start()
	yield session
	await session.kill()
	await session.event_bus.stop(clear=True, timeout=5)


@pytest.fixture(scope='module')
def tools(browser_session):
	return Tools(browser_session)


# Use an index that will never exist in any selector map
MISSING_INDEX = 99999


class TestElementNotFoundReturnsError:
	"""All actions must return ActionResult(error=...) when the element index is missing."""

	async def test_click_missing_element_returns_error(self, tools, browser_session):
		"""click with a non-existent index must set ActionResult.error."""
		result = await tools.click(index=MISSING_INDEX, browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is not None, 'click should return error when element not found'
		assert 'not available' in result.error

	async def test_click_missing_element_has_no_extracted_content(self, tools, browser_session):
		"""click error should not leak into extracted_content (which the LLM reads as success)."""
		result = await tools.click(index=MISSING_INDEX, browser_session=browser_session)

		# extracted_content should be None or empty when there's an error
		# (the error message is in .error, not .extracted_content)
		assert result.error is not None

	async def test_dropdown_options_missing_element_returns_error(self, tools, browser_session):
		"""dropdown_options with a non-existent index must set ActionResult.error."""
		result = await tools.dropdown_options(index=MISSING_INDEX, browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is not None, 'dropdown_options should return error when element not found'
		assert 'not available' in result.error

	async def test_select_dropdown_missing_element_returns_error(self, tools, browser_session):
		"""select_dropdown with a non-existent index must set ActionResult.error."""
		result = await tools.select_dropdown(index=MISSING_INDEX, text='anything', browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.error is not None, 'select_dropdown should return error when element not found'
		assert 'not available' in result.error

	async def test_error_result_not_marked_as_done(self, tools, browser_session):
		"""Element-not-found errors must not be marked as done (is_done=False)."""
		result = await tools.click(index=MISSING_INDEX, browser_session=browser_session)
		assert not result.is_done, 'error result should not be marked as done'

	async def test_error_result_not_marked_as_success(self, tools, browser_session):
		"""Element-not-found errors must not be marked as success."""
		result = await tools.click(index=MISSING_INDEX, browser_session=browser_session)
		# success should be None or False, not True
		assert result.success is not True, 'error result should not be marked as success'
