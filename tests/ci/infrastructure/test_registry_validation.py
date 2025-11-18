"""
Comprehensive tests for the action registry system - Validation and patterns.

Tests cover:
1. Type 1 and Type 2 patterns
2. Validation rules
3. Decorated function behavior
4. Parameter model generation
5. Parameter ordering
"""

import asyncio
import logging

import pytest
from pydantic import Field

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.tools.registry.service import Registry
from browser_use.tools.registry.views import ActionModel as BaseActionModel
from tests.ci.conftest import create_mock_llm

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class TestType1Pattern:
	"""Test Type 1 Pattern: Pydantic model first (from normalization tests)"""

	def test_type1_with_param_model(self):
		"""Type 1: action(params: Model, special_args...) should work"""
		registry = Registry()

		class ClickAction(BaseActionModel):
			index: int
			delay: float = 0.0

		@registry.action('Click element', param_model=ClickAction)
		async def click_element(params: ClickAction, browser_session: BrowserSession):
			return ActionResult(extracted_content=f'Clicked {params.index}')

		# Verify registration
		assert 'click_element' in registry.registry.actions
		action = registry.registry.actions['click_element']
		assert action.param_model == ClickAction

		# Verify decorated function signature (should be kwargs-only)
		import inspect

		sig = inspect.signature(click_element)
		params = list(sig.parameters.values())

		# Should have no positional-only or positional-or-keyword params
		for param in params:
			assert param.kind in (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.VAR_KEYWORD)

	def test_type1_with_multiple_special_params(self):
		"""Type 1 with multiple special params should work"""
		registry = Registry()

		class ExtractAction(BaseActionModel):
			goal: str
			include_links: bool = False

		from browser_use.llm.base import BaseChatModel

		@registry.action('Extract content', param_model=ExtractAction)
		async def extract_content(params: ExtractAction, browser_session: BrowserSession, page_extraction_llm: BaseChatModel):
			return ActionResult(extracted_content=params.goal)

		assert 'extract_content' in registry.registry.actions


class TestType2Pattern:
	"""Test Type 2 Pattern: loose parameters (from normalization tests)"""

	def test_type2_simple_action(self):
		"""Type 2: action(arg1, arg2, special_args...) should work"""
		registry = Registry()

		@registry.action('Fill field')
		async def fill_field(index: int, text: str, browser_session: BrowserSession):
			return ActionResult(extracted_content=f'Filled {index} with {text}')

		# Verify registration
		assert 'fill_field' in registry.registry.actions
		action = registry.registry.actions['fill_field']

		# Should auto-generate param model
		assert action.param_model is not None
		assert 'index' in action.param_model.model_fields
		assert 'text' in action.param_model.model_fields

	def test_type2_with_defaults(self):
		"""Type 2 with default values should preserve defaults"""
		registry = Registry()

		@registry.action('Scroll page')
		async def scroll_page(direction: str = 'down', amount: int = 100, browser_session: BrowserSession = None):  # type: ignore
			return ActionResult(extracted_content=f'Scrolled {direction} by {amount}')

		action = registry.registry.actions['scroll_page']
		# Check that defaults are preserved in generated model
		schema = action.param_model.model_json_schema()
		assert schema['properties']['direction']['default'] == 'down'
		assert schema['properties']['amount']['default'] == 100

	def test_type2_no_action_params(self):
		"""Type 2 with only special params should work"""
		registry = Registry()

		@registry.action('Save PDF')
		async def save_pdf(browser_session: BrowserSession):
			return ActionResult(extracted_content='Saved PDF')

		action = registry.registry.actions['save_pdf']
		# Should have empty or minimal param model
		fields = action.param_model.model_fields
		assert len(fields) == 0 or all(f in ['title'] for f in fields)

	def test_no_special_params_action(self):
		"""Test action with no special params (like wait action in Tools)"""
		registry = Registry()

		@registry.action('Wait for x seconds default 3')
		async def wait(seconds: int = 3):
			await asyncio.sleep(seconds)
			return ActionResult(extracted_content=f'Waited {seconds} seconds')

		# Should register successfully
		assert 'wait' in registry.registry.actions
		action = registry.registry.actions['wait']

		# Should have seconds in param model
		assert 'seconds' in action.param_model.model_fields

		# Should preserve default value
		schema = action.param_model.model_json_schema()
		assert schema['properties']['seconds']['default'] == 3


class TestValidationRules:
	"""Test validation rules for action registration (from normalization tests)"""

	def test_error_on_kwargs_in_original_function(self):
		"""Should error if original function has kwargs"""
		registry = Registry()

		with pytest.raises(ValueError, match='kwargs.*not allowed'):

			@registry.action('Bad action')
			async def bad_action(index: int, browser_session: BrowserSession, **kwargs):
				pass

	def test_error_on_special_param_name_with_wrong_type(self):
		"""Should error if special param name used with wrong type"""
		registry = Registry()

		# Using 'browser_session' with wrong type should error
		with pytest.raises(ValueError, match='conflicts with special argument.*browser_session: BrowserSession'):

			@registry.action('Bad session')
			async def bad_session(browser_session: str):
				pass

	def test_special_params_must_match_type(self):
		"""Special params with correct types should work"""
		registry = Registry()

		@registry.action('Good action')
		async def good_action(
			index: int,
			browser_session: BrowserSession,  # Correct type
		):
			return ActionResult()

		assert 'good_action' in registry.registry.actions


class TestDecoratedFunctionBehavior:
	"""Test behavior of decorated action functions (from normalization tests)"""

	async def test_decorated_function_only_accepts_kwargs(self):
		"""Decorated functions should only accept kwargs, no positional args"""
		registry = Registry()

		class MockBrowserSession:
			async def get_current_page(self):
				return None

		@registry.action('Click')
		async def click(index: int, browser_session: BrowserSession):
			return ActionResult()

		# Should raise error when called with positional args
		with pytest.raises(TypeError, match='positional arguments'):
			await click(5, MockBrowserSession())

	async def test_decorated_function_accepts_params_model(self):
		"""Decorated function should accept params as model"""
		registry = Registry()

		class MockBrowserSession:
			async def get_current_page(self):
				return None

		@registry.action('Input text')
		async def input_text(index: int, text: str, browser_session: BrowserSession):
			return ActionResult(extracted_content=f'{index}:{text}')

		# Get the generated param model class
		action = registry.registry.actions['input_text']
		ParamsModel = action.param_model

		# Should work with params model
		result = await input_text(params=ParamsModel(index=5, text='hello'), browser_session=MockBrowserSession())
		assert result.extracted_content == '5:hello'

	async def test_decorated_function_ignores_extra_kwargs(self):
		"""Decorated function should ignore extra kwargs for easy unpacking"""
		registry = Registry()

		@registry.action('Simple action')
		async def simple_action(value: int):
			return ActionResult(extracted_content=str(value))

		# Should work even with extra kwargs
		special_context = {
			'browser_session': None,
			'page_extraction_llm': create_mock_llm(),
			'context': {'extra': 'data'},
			'unknown_param': 'ignored',
		}

		action = registry.registry.actions['simple_action']
		ParamsModel = action.param_model

		result = await simple_action(params=ParamsModel(value=42), **special_context)
		assert result.extracted_content == '42'


class TestParamsModelGeneration:
	"""Test automatic parameter model generation (from normalization tests)"""

	def test_generates_model_from_non_special_args(self):
		"""Should generate param model from non-special positional args"""
		registry = Registry()

		@registry.action('Complex action')
		async def complex_action(
			query: str,
			max_results: int,
			include_images: bool = True,
			browser_session: BrowserSession = None,  # type: ignore
		):
			return ActionResult()

		action = registry.registry.actions['complex_action']
		model_fields = action.param_model.model_fields

		# Should include only non-special params
		assert 'query' in model_fields
		assert 'max_results' in model_fields
		assert 'include_images' in model_fields

		# Should NOT include special params
		assert 'browser_session' not in model_fields

	def test_preserves_type_annotations(self):
		"""Generated model should preserve type annotations"""
		registry = Registry()

		@registry.action('Typed action')
		async def typed_action(
			count: int,
			rate: float,
			enabled: bool,
			name: str | None = None,
			browser_session: BrowserSession = None,  # type: ignore
		):
			return ActionResult()

		action = registry.registry.actions['typed_action']
		schema = action.param_model.model_json_schema()

		# Check types are preserved
		assert schema['properties']['count']['type'] == 'integer'
		assert schema['properties']['rate']['type'] == 'number'
		assert schema['properties']['enabled']['type'] == 'boolean'
		# Optional should allow null
		assert 'null' in schema['properties']['name']['anyOf'][1]['type']


class TestParameterOrdering:
	"""Test mixed ordering of parameters (from normalization tests)"""

	def test_mixed_param_ordering(self):
		"""Should handle any ordering of action params and special params"""
		registry = Registry()
		from browser_use.llm.base import BaseChatModel

		# Special params mixed throughout
		@registry.action('Mixed params')
		async def mixed_action(
			first: str,
			browser_session: BrowserSession,
			second: int,
			third: bool = True,
			page_extraction_llm: BaseChatModel = None,  # type: ignore
		):
			return ActionResult()

		action = registry.registry.actions['mixed_action']
		model_fields = action.param_model.model_fields

		# Only action params in model
		assert set(model_fields.keys()) == {'first', 'second', 'third'}
		assert model_fields['third'].default is True

	def test_extract_content_pattern_registration(self):
		"""Test that the extract_content pattern with mixed params registers correctly"""
		registry = Registry()

		# This is the problematic pattern: positional arg, then special args, then kwargs with defaults
		@registry.action('Extract content from page')
		async def extract_content(
			goal: str,
			page_extraction_llm,
			include_links: bool = False,
		):
			return ActionResult(extracted_content=f'Goal: {goal}, include_links: {include_links}')

		# Verify registration
		assert 'extract_content' in registry.registry.actions
		action = registry.registry.actions['extract_content']

		# Check that the param model only includes user-facing params
		model_fields = action.param_model.model_fields
		assert 'goal' in model_fields
		assert 'include_links' in model_fields
		assert model_fields['include_links'].default is False

		# Special params should NOT be in the model
		assert 'page' not in model_fields
		assert 'page_extraction_llm' not in model_fields

		# Verify the action was properly registered
		assert action.name == 'extract_content'
		assert action.description == 'Extract content from page'


class TestParamsModelArgsAndKwargs:
	async def test_browser_session_double_kwarg(self):
		"""Run the test to diagnose browser_session parameter issue

		This test demonstrates the problem and our fix. The issue happens because:

		1. In tools/service.py, we have:
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

		from browser_use.tools.registry.service import Registry
		from browser_use.tools.registry.views import ActionModel

		# Simple context for testing
		class TestContext:
			pass

		class MockBrowserSession:
			async def get_current_page(self):
				return None

		browser_session = MockBrowserSession()

		# Create registry
		registry = Registry[TestContext]()

		# Model that doesn't include browser_session (renamed to avoid pytest collecting it)
		class CellActionParams(ActionModel):
			value: str = Field(description='Test value')

		# Model that includes browser_session
		class ModelWithBrowser(ActionModel):
			value: str = Field(description='Test value')
			browser_session: BrowserSession = None  # type: ignore

		# Create a custom param model for select_cell_or_range
		class CellRangeParams(ActionModel):
			cell_or_range: str = Field(description='Cell or range to select')

		# Use the provided real browser session

		# Test with the real issue: select_cell_or_range
		# logger.info('\n\n=== Test: Simulating select_cell_or_range issue with correct model ===')

		# Define the function without using our registry - this will be a helper function
		async def _select_cell_or_range(browser_session, cell_or_range):
			"""Helper function for select_cell_or_range"""
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
				'select_cell_or_range',
				{'cell_or_range': 'A1:F100'},
				browser_session=browser_session,  # type: ignore
			)
			# logger.info(f'Success! Result: {result1}')
		except Exception as e:
			logger.error(f'Error: {str(e)}')

		# Test the fixed version (using positional args)
		# logger.info('\n--- Testing fixed version (positional args) ---')
		try:
			result2 = await registry.execute_action(
				'select_cell_or_range_fixed',
				{'cell_or_range': 'A1:F100'},
				browser_session=browser_session,  # type: ignore
			)
			# logger.info(f'Success! Result: {result2}')
		except Exception as e:
			logger.error(f'Error: {str(e)}')

		# Test with kwargs version that simulates what Registry.execute_action does
		# logger.info('\n--- Testing kwargs simulation version ---')
		try:
			result3 = await registry.execute_action(
				'select_with_kwargs',
				{'cell_or_range': 'A1:F100'},
				browser_session=browser_session,  # type: ignore
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
