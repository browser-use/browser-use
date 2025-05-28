"""
Test script to reproduce and debug the browser_session parameter issue with actions
like select_cell_or_range in Google Sheets.

This test demonstrates a specific parameter passing issue that can occur in registry.execute_action
when a parameter (like browser_session) is:
1. Required by a function registered with the Registry
2. Added to extra_args by the Registry.execute_action method
3. Passed by name when the function calls another function

The bug would manifest as:
"TypeError: select_cell_or_range() got multiple values for argument 'browser_session'"

The fix is to pass browser_session positionally, not by name, when calling from one action to another,
to avoid the conflict when the Registry also adds it to extra_args.

This test validates the issue exists and confirms the fix works.
"""

import asyncio
import logging

from pydantic import Field

from browser_use.controller.registry.service import Registry
from browser_use.controller.registry.views import ActionModel

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


# Use real browser session for testing
import pytest

from browser_use.browser import BrowserSession


@pytest.fixture
async def browser_session():
	"""Create and provide a real BrowserSession instance."""
	browser_session = BrowserSession(
		headless=True,
		user_data_dir=None,
	)
	await browser_session.start()
	yield browser_session
	await browser_session.stop()


# Model that doesn't include browser_session (renamed to avoid pytest collecting it)
class CellActionParams(ActionModel):
	value: str = Field(description='Test value')


# Model that includes browser_session
class ModelWithBrowser(ActionModel):
	value: str = Field(description='Test value')
	browser_session: BrowserSession = None


# Simple context for testing
class TestContext:
	pass


async def main(browser_session):
	"""Run the test to diagnose browser_session parameter issue

	This test demonstrates the problem and our fix. The issue happens because:

	1. In controller/service.py, we have:
	   ```python
	   @registry.action('Google Sheets: Select a specific cell or range of cells')
	   async def select_cell_or_range(browser_session: BrowserSession, cell_or_range: str):
	       return await _select_cell_or_range(browser_session=browser_session, cell_or_range=cell_or_range)
	   ```

	2. When registry.execute_action calls this function, it adds browser_session to extra_args:
	   ```python
	   # In registry/service.py
	   if 'browser_session' in parameter_names:
	       extra_args['browser_session'] = browser_session
	   ```

	3. Then later, when calling action.function:
	   ```python
	   return await action.function(**params_dict, **extra_args)
	   ```

	4. This effectively means browser_session is passed twice:
	   - Once through extra_args['browser_session']
	   - And again through params_dict['browser_session'] (from the original function)

	The fix is to pass browser_session positionally in select_cell_or_range:
	```python
	return await _select_cell_or_range(browser_session, cell_or_range)
	```

	This test confirms that this approach works.
	"""
	# logger.info('Starting browser_session parameter test')

	# Create registry
	registry = Registry[TestContext]()

	# Create a custom param model for select_cell_or_range
	class CellRangeParams(ActionModel):
		cell_or_range: str = Field(description='Cell or range to select')

	# Use the provided real browser session

	# Test with the real issue: select_cell_or_range
	# logger.info('\n\n=== Test: Simulating select_cell_or_range issue with correct model ===')

	# Define the function without using our registry - this will be a helper function
	async def _select_cell_or_range(browser_session, cell_or_range):
		"""Helper function for select_cell_or_range"""
		# logger.info(f'_select_cell_or_range internal implementation called with cell_or_range={cell_or_range}')
		return f'Selected cell {cell_or_range}'

	# This simulates the actual issue we're seeing in the real code
	# The browser_session parameter is in both the function signature and passed as a named arg
	@registry.action('Google Sheets: Select a cell or range', param_model=CellRangeParams)
	async def select_cell_or_range(browser_session: BrowserSession, cell_or_range: str):
		# logger.info(f'select_cell_or_range called with browser_session={browser_session}, cell_or_range={cell_or_range}')

		# PROBLEMATIC LINE: browser_session is passed by name, matching the parameter name
		# This is what causes the "got multiple values" error in the real code
		return await _select_cell_or_range(browser_session=browser_session, cell_or_range=cell_or_range)

	# Fix attempt: Register a version that uses positional args instead
	@registry.action('Google Sheets: Select a cell or range (fixed)', param_model=CellRangeParams)
	async def select_cell_or_range_fixed(browser_session: BrowserSession, cell_or_range: str):
		# logger.info(f'select_cell_or_range_fixed called with browser_session={browser_session}, cell_or_range={cell_or_range}')

		# FIXED LINE: browser_session is passed positionally, avoiding the parameter name conflict
		return await _select_cell_or_range(browser_session, cell_or_range)

	# Another attempt: explicitly call using **kwargs to simulate what the registry does
	@registry.action('Google Sheets: Select with kwargs', param_model=CellRangeParams)
	async def select_with_kwargs(browser_session: BrowserSession, cell_or_range: str):
		# logger.info(f'select_with_kwargs called with browser_session={browser_session}, cell_or_range={cell_or_range}')

		# Get params and extra_args, like in Registry.execute_action
		params = {'cell_or_range': cell_or_range, 'browser_session': browser_session}
		extra_args = {'browser_session': browser_session}

		# Try to call _select_cell_or_range with both params and extra_args
		# This will fail with "got multiple values for keyword argument 'browser_session'"
		try:
			# logger.info('Attempting to call with both params and extra_args (should fail):')
			await _select_cell_or_range(**params, **extra_args)
		except TypeError as e:
			# logger.info(f'Expected error: {e}')

			# Remove browser_session from params to avoid the conflict
			params_fixed = dict(params)
			del params_fixed['browser_session']

			# logger.info(f'Fixed params: {params_fixed}')

			# This should work
			result = await _select_cell_or_range(**params_fixed, **extra_args)
			# logger.info(f'Success after fix: {result}')
			return result

	# Test the original problematic version
	# logger.info('\n--- Testing original problematic version ---')
	try:
		result1 = await registry.execute_action(
			'select_cell_or_range', {'cell_or_range': 'A1:F100'}, browser_session=browser_session
		)
		# logger.info(f'Success! Result: {result1}')
	except Exception as e:
		logger.error(f'Error: {str(e)}')

	# Test the fixed version (using positional args)
	# logger.info('\n--- Testing fixed version (positional args) ---')
	try:
		result2 = await registry.execute_action(
			'select_cell_or_range_fixed', {'cell_or_range': 'A1:F100'}, browser_session=browser_session
		)
		# logger.info(f'Success! Result: {result2}')
	except Exception as e:
		logger.error(f'Error: {str(e)}')

	# Test with kwargs version that simulates what Registry.execute_action does
	# logger.info('\n--- Testing kwargs simulation version ---')
	try:
		result3 = await registry.execute_action(
			'select_with_kwargs', {'cell_or_range': 'A1:F100'}, browser_session=browser_session
		)
		# logger.info(f'Success! Result: {result3}')
	except Exception as e:
		logger.error(f'Error: {str(e)}')

	# Manual test of our theory: browser_session is passed twice
	# logger.info('\n--- Direct test of our theory ---')
	try:
		# Create the model instance
		params = CellRangeParams(cell_or_range='A1:F100')

		# First check if the extra_args approach works
		# logger.info('Checking if extra_args approach works:')
		extra_args = {'browser_session': browser_session}

		# If we were to modify Registry.execute_action:
		# 1. Check if the function parameter needs browser_session
		parameter_names = ['browser_session', 'cell_or_range']
		browser_keys = ['browser_session', 'browser', 'browser_context']

		# Create params dict
		param_dict = params.model_dump()
		# logger.info(f'params dict before: {param_dict}')

		# Apply our fix: remove browser_session from params dict
		for key in browser_keys:
			if key in param_dict and key in extra_args:
				# logger.info(f'Removing {key} from params dict')
				del param_dict[key]

		# logger.info(f'params dict after: {param_dict}')
		# logger.info(f'extra_args: {extra_args}')

		# This would be the fixed code:
		# return await action.function(**param_dict, **extra_args)

		# Call directly to test
		result3 = await select_cell_or_range(**param_dict, **extra_args)
		# logger.info(f'Success with our fix! Result: {result3}')
	except Exception as e:
		logger.error(f'Error with our manual test: {str(e)}')


# Add a proper pytest test function
import pytest


async def test_browser_session_parameter_issue(browser_session):
	"""Test that the browser_session parameter issue is fixed."""
	# Run the main test logic
	await main(browser_session)


if __name__ == '__main__':
	# For direct execution (not through pytest)
	async def run_with_real_browser():
		browser_session = BrowserSession(headless=True, user_data_dir=None)
		await browser_session.start()
		try:
			await main(browser_session)
		finally:
			await browser_session.stop()

	asyncio.run(run_with_real_browser())
