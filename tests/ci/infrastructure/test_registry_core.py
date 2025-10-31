"""
Comprehensive tests for the action registry system - Core functionality.

Tests cover:
1. Existing parameter patterns (individual params, pydantic models)
2. Special parameter injection (browser_session, page_extraction_llm, etc.)
3. Action-to-action calling scenarios
4. Mixed parameter patterns
5. Registry execution edge cases
"""

import asyncio
import logging

import pytest
from pydantic import Field
from pytest_httpserver import HTTPServer
from pytest_httpserver.httpserver import HandlerType

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.llm.messages import UserMessage
from browser_use.tools.registry.service import Registry
from browser_use.tools.registry.views import ActionModel as BaseActionModel
from browser_use.tools.views import (
	ClickElementAction,
	InputTextAction,
	NoParamsAction,
	SearchAction,
)
from tests.ci.conftest import create_mock_llm

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class TestContext:
	"""Simple context for testing"""

	pass


# Test parameter models
class SimpleParams(BaseActionModel):
	"""Simple parameter model"""

	value: str = Field(description='Test value')


class ComplexParams(BaseActionModel):
	"""Complex parameter model with multiple fields"""

	text: str = Field(description='Text input')
	number: int = Field(description='Number input', default=42)
	optional_flag: bool = Field(description='Optional boolean', default=False)


# Test fixtures
@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server that serves static content."""
	server = HTTPServer()
	server.start()

	# Add a simple test page that can handle multiple requests
	server.expect_request('/test', handler_type=HandlerType.PERMANENT).respond_with_data(
		'<html><head><title>Test Page</title></head><body><h1>Test Page</h1><p>Hello from test page</p></body></html>',
		content_type='text/html',
	)

	yield server

	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	"""Return the base URL for the test HTTP server."""
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
def mock_llm():
	"""Create a mock LLM"""
	return create_mock_llm()


@pytest.fixture(scope='function')
def registry():
	"""Create a fresh registry for each test"""
	return Registry[TestContext]()


@pytest.fixture(scope='function')
async def browser_session(base_url):
	"""Create a real BrowserSession for testing"""
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
		)
	)
	await browser_session.start()
	from browser_use.browser.events import NavigateToUrlEvent

	browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/test'))
	await asyncio.sleep(0.5)  # Wait for navigation
	yield browser_session
	await browser_session.kill()


class TestActionRegistryParameterPatterns:
	"""Test different parameter patterns that should all continue to work"""

	async def test_individual_parameters_no_browser(self, registry):
		"""Test action with individual parameters, no special injection"""

		@registry.action('Simple action with individual params')
		async def simple_action(text: str, number: int = 10):
			return ActionResult(extracted_content=f'Text: {text}, Number: {number}')

		# Test execution
		result = await registry.execute_action('simple_action', {'text': 'hello', 'number': 42})

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Text: hello, Number: 42' in result.extracted_content

	async def test_individual_parameters_with_browser(self, registry, browser_session, base_url):
		"""Test action with individual parameters plus browser_session injection"""

		@registry.action('Action with individual params and browser')
		async def action_with_browser(text: str, browser_session: BrowserSession):
			url = await browser_session.get_current_page_url()
			return ActionResult(extracted_content=f'Text: {text}, URL: {url}')

		# Navigate to test page first
		from browser_use.browser.events import NavigateToUrlEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/test', new_tab=True))
		await event

		# Test execution
		result = await registry.execute_action('action_with_browser', {'text': 'hello'}, browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Text: hello, URL:' in result.extracted_content
		assert base_url in result.extracted_content

	async def test_pydantic_model_parameters(self, registry, browser_session, base_url):
		"""Test action that takes a pydantic model as first parameter"""

		@registry.action('Action with pydantic model', param_model=ComplexParams)
		async def pydantic_action(params: ComplexParams, browser_session: BrowserSession):
			url = await browser_session.get_current_page_url()
			return ActionResult(
				extracted_content=f'Text: {params.text}, Number: {params.number}, Flag: {params.optional_flag}, URL: {url}'
			)

		# Navigate to test page first
		from browser_use.browser.events import NavigateToUrlEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/test', new_tab=True))
		await event

		# Test execution
		result = await registry.execute_action(
			'pydantic_action', {'text': 'test', 'number': 100, 'optional_flag': True}, browser_session=browser_session
		)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Text: test, Number: 100, Flag: True' in result.extracted_content
		assert base_url in result.extracted_content

	async def test_mixed_special_parameters(self, registry, browser_session, base_url, mock_llm):
		"""Test action with multiple special injected parameters"""

		from browser_use.llm.base import BaseChatModel

		@registry.action('Action with multiple special params')
		async def multi_special_action(
			text: str,
			browser_session: BrowserSession,
			page_extraction_llm: BaseChatModel,
			available_file_paths: list,
		):
			llm_response = await page_extraction_llm.ainvoke([UserMessage(content='test')])
			files = available_file_paths or []
			url = await browser_session.get_current_page_url()

			return ActionResult(
				extracted_content=f'Text: {text}, URL: {url}, LLM: {llm_response.completion}, Files: {len(files)}'
			)

		# Navigate to test page first
		from browser_use.browser.events import NavigateToUrlEvent

		event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/test', new_tab=True))
		await event

		# Test execution
		result = await registry.execute_action(
			'multi_special_action',
			{'text': 'hello'},
			browser_session=browser_session,
			page_extraction_llm=mock_llm,
			available_file_paths=['file1.txt', 'file2.txt'],
		)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Text: hello' in result.extracted_content
		assert base_url in result.extracted_content
		# The mock LLM returns a JSON response
		assert '"Task completed successfully"' in result.extracted_content
		assert 'Files: 2' in result.extracted_content

	async def test_no_params_action(self, registry, browser_session):
		"""Test action with NoParamsAction model"""

		@registry.action('No params action', param_model=NoParamsAction)
		async def no_params_action(params: NoParamsAction, browser_session: BrowserSession):
			url = await browser_session.get_current_page_url()
			return ActionResult(extracted_content=f'No params action executed on {url}')

		# Test execution with any parameters (should be ignored)
		result = await registry.execute_action(
			'no_params_action', {'random': 'data', 'should': 'be', 'ignored': True}, browser_session=browser_session
		)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'No params action executed on' in result.extracted_content
		assert '/test' in result.extracted_content


class TestActionToActionCalling:
	"""Test scenarios where actions call other actions"""

	async def test_action_calling_action_with_kwargs(self, registry, browser_session):
		"""Test action calling another action using kwargs (current problematic pattern)"""

		# Helper function that actions can call
		async def helper_function(browser_session: BrowserSession, data: str):
			url = await browser_session.get_current_page_url()
			return f'Helper processed: {data} on {url}'

		@registry.action('First action')
		async def first_action(text: str, browser_session: BrowserSession):
			# This should work without parameter conflicts
			result = await helper_function(browser_session=browser_session, data=text)
			return ActionResult(extracted_content=f'First: {result}')

		@registry.action('Calling action')
		async def calling_action(message: str, browser_session: BrowserSession):
			# Call the first action through the registry (simulates action-to-action calling)
			intermediate_result = await registry.execute_action(
				'first_action', {'text': message}, browser_session=browser_session
			)
			return ActionResult(extracted_content=f'Called result: {intermediate_result.extracted_content}')

		# Test the calling chain
		result = await registry.execute_action('calling_action', {'message': 'test'}, browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Called result: First: Helper processed: test on' in result.extracted_content
		assert '/test' in result.extracted_content

	async def test_google_sheets_style_calling_pattern(self, registry, browser_session):
		"""Test the specific pattern from Google Sheets actions that causes the error"""

		# Simulate the _select_cell_or_range helper function
		async def _select_cell_or_range(browser_session: BrowserSession, cell_or_range: str):
			url = await browser_session.get_current_page_url()
			return ActionResult(extracted_content=f'Selected cell {cell_or_range} on {url}')

		@registry.action('Select cell or range')
		async def select_cell_or_range(cell_or_range: str, browser_session: BrowserSession):
			# This pattern now works with kwargs
			return await _select_cell_or_range(browser_session=browser_session, cell_or_range=cell_or_range)

		@registry.action('Select cell or range (fixed)')
		async def select_cell_or_range_fixed(cell_or_range: str, browser_session: BrowserSession):
			# This pattern also works
			return await _select_cell_or_range(browser_session, cell_or_range)

		@registry.action('Update range contents')
		async def update_range_contents(range_name: str, new_contents: str, browser_session: BrowserSession):
			# This action calls select_cell_or_range, simulating the real Google Sheets pattern
			# Get the action's param model to call it properly
			action = registry.registry.actions['select_cell_or_range_fixed']
			params = action.param_model(cell_or_range=range_name)
			await select_cell_or_range_fixed(cell_or_range=range_name, browser_session=browser_session)
			return ActionResult(extracted_content=f'Updated range {range_name} with {new_contents}')

		# Test the fixed version (should work)
		result_fixed = await registry.execute_action(
			'select_cell_or_range_fixed', {'cell_or_range': 'A1:F100'}, browser_session=browser_session
		)
		assert result_fixed.extracted_content is not None
		assert 'Selected cell A1:F100 on' in result_fixed.extracted_content
		assert '/test' in result_fixed.extracted_content

		# Test the chained calling pattern
		result_chain = await registry.execute_action(
			'update_range_contents', {'range_name': 'B2:D4', 'new_contents': 'test data'}, browser_session=browser_session
		)
		assert result_chain.extracted_content is not None
		assert 'Updated range B2:D4 with test data' in result_chain.extracted_content

		# Test the problematic version (should work with enhanced registry)
		result_problematic = await registry.execute_action(
			'select_cell_or_range', {'cell_or_range': 'A1:F100'}, browser_session=browser_session
		)
		# With the enhanced registry, this should succeed
		assert result_problematic.extracted_content is not None
		assert 'Selected cell A1:F100 on' in result_problematic.extracted_content
		assert '/test' in result_problematic.extracted_content

	async def test_complex_action_chain(self, registry, browser_session):
		"""Test a complex chain of actions calling other actions"""

		@registry.action('Base action')
		async def base_action(value: str, browser_session: BrowserSession):
			url = await browser_session.get_current_page_url()
			return ActionResult(extracted_content=f'Base: {value} on {url}')

		@registry.action('Middle action')
		async def middle_action(input_val: str, browser_session: BrowserSession):
			# Call base action
			base_result = await registry.execute_action(
				'base_action', {'value': f'processed-{input_val}'}, browser_session=browser_session
			)
			return ActionResult(extracted_content=f'Middle: {base_result.extracted_content}')

		@registry.action('Top action')
		async def top_action(original: str, browser_session: BrowserSession):
			# Call middle action
			middle_result = await registry.execute_action(
				'middle_action', {'input_val': f'enhanced-{original}'}, browser_session=browser_session
			)
			return ActionResult(extracted_content=f'Top: {middle_result.extracted_content}')

		# Test the full chain
		result = await registry.execute_action('top_action', {'original': 'test'}, browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Top: Middle: Base: processed-enhanced-test on' in result.extracted_content
		assert '/test' in result.extracted_content


class TestRegistryEdgeCases:
	"""Test edge cases and error conditions"""

	async def test_decorated_action_rejects_positional_args(self, registry, browser_session):
		"""Test that decorated actions reject positional arguments"""

		@registry.action('Action that should reject positional args')
		async def test_action(cell_or_range: str, browser_session: BrowserSession):
			url = await browser_session.get_current_page_url()
			return ActionResult(extracted_content=f'Selected cell {cell_or_range} on {url}')

		# Test that calling with positional arguments raises TypeError
		with pytest.raises(
			TypeError, match='test_action\\(\\) does not accept positional arguments, only keyword arguments are allowed'
		):
			await test_action('A1:B2', browser_session)

		# Test that calling with keyword arguments works
		result = await test_action(browser_session=browser_session, cell_or_range='A1:B2')
		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Selected cell A1:B2 on' in result.extracted_content

	async def test_missing_required_browser_session(self, registry):
		"""Test that actions requiring browser_session fail appropriately when not provided"""

		@registry.action('Requires browser')
		async def requires_browser(text: str, browser_session: BrowserSession):
			url = await browser_session.get_current_page_url()
			return ActionResult(extracted_content=f'Text: {text}, URL: {url}')

		# Should raise RuntimeError when browser_session is required but not provided
		with pytest.raises(RuntimeError, match='requires browser_session but none provided'):
			await registry.execute_action(
				'requires_browser',
				{'text': 'test'},
				# No browser_session provided
			)

	async def test_missing_required_llm(self, registry, browser_session):
		"""Test that actions requiring page_extraction_llm fail appropriately when not provided"""

		from browser_use.llm.base import BaseChatModel

		@registry.action('Requires LLM')
		async def requires_llm(text: str, browser_session: BrowserSession, page_extraction_llm: BaseChatModel):
			url = await browser_session.get_current_page_url()
			llm_response = await page_extraction_llm.ainvoke([UserMessage(content='test')])
			return ActionResult(extracted_content=f'Text: {text}, LLM: {llm_response.completion}')

		# Should raise RuntimeError when page_extraction_llm is required but not provided
		with pytest.raises(RuntimeError, match='requires page_extraction_llm but none provided'):
			await registry.execute_action(
				'requires_llm',
				{'text': 'test'},
				browser_session=browser_session,
				# No page_extraction_llm provided
			)

	async def test_invalid_parameters(self, registry, browser_session):
		"""Test handling of invalid parameters"""

		@registry.action('Typed action')
		async def typed_action(number: int, browser_session: BrowserSession):
			return ActionResult(extracted_content=f'Number: {number}')

		# Should raise RuntimeError when parameter validation fails
		with pytest.raises(RuntimeError, match='Invalid parameters'):
			await registry.execute_action(
				'typed_action',
				{'number': 'not a number'},  # Invalid type
				browser_session=browser_session,
			)

	async def test_nonexistent_action(self, registry, browser_session):
		"""Test calling a non-existent action"""

		with pytest.raises(ValueError, match='Action nonexistent_action not found'):
			await registry.execute_action('nonexistent_action', {'param': 'value'}, browser_session=browser_session)

	async def test_sync_action_wrapper(self, registry, browser_session):
		"""Test that sync functions are properly wrapped to be async"""

		@registry.action('Sync action')
		def sync_action(text: str, browser_session: BrowserSession):
			# This is a sync function that should be wrapped
			return ActionResult(extracted_content=f'Sync: {text}')

		# Should work even though the original function is sync
		result = await registry.execute_action('sync_action', {'text': 'test'}, browser_session=browser_session)

		assert isinstance(result, ActionResult)
		assert result.extracted_content is not None
		assert 'Sync: test' in result.extracted_content

	async def test_excluded_actions(self, browser_session):
		"""Test that excluded actions are not registered"""

		registry_with_exclusions = Registry[TestContext](exclude_actions=['excluded_action'])

		@registry_with_exclusions.action('Excluded action')
		async def excluded_action(text: str):
			return ActionResult(extracted_content=f'Should not execute: {text}')

		@registry_with_exclusions.action('Included action')
		async def included_action(text: str):
			return ActionResult(extracted_content=f'Should execute: {text}')

		# Excluded action should not be in registry
		assert 'excluded_action' not in registry_with_exclusions.registry.actions
		assert 'included_action' in registry_with_exclusions.registry.actions

		# Should raise error when trying to execute excluded action
		with pytest.raises(ValueError, match='Action excluded_action not found'):
			await registry_with_exclusions.execute_action('excluded_action', {'text': 'test'})

		# Included action should work
		result = await registry_with_exclusions.execute_action('included_action', {'text': 'test'})
		assert result.extracted_content is not None
		assert 'Should execute: test' in result.extracted_content


class TestExistingToolsActions:
	"""Test that existing tools actions continue to work"""

	async def test_existing_action_models(self, registry, browser_session):
		"""Test that existing action parameter models work correctly"""

		@registry.action('Test search', param_model=SearchAction)
		async def test_search(params: SearchAction, browser_session: BrowserSession):
			return ActionResult(extracted_content=f'Searched for: {params.query}')

		@registry.action('Test click', param_model=ClickElementAction)
		async def test_click(params: ClickElementAction, browser_session: BrowserSession):
			return ActionResult(extracted_content=f'Clicked element: {params.index}')

		@registry.action('Test input', param_model=InputTextAction)
		async def test_input(params: InputTextAction, browser_session: BrowserSession):
			return ActionResult(extracted_content=f'Input text: {params.text} at index: {params.index}')

		# Test SearchGoogleAction
		result1 = await registry.execute_action('test_search', {'query': 'python testing'}, browser_session=browser_session)
		assert result1.extracted_content is not None
		assert 'Searched for: python testing' in result1.extracted_content

		# Test ClickElementAction
		result2 = await registry.execute_action('test_click', {'index': 42}, browser_session=browser_session)
		assert result2.extracted_content is not None
		assert 'Clicked element: 42' in result2.extracted_content

		# Test InputTextAction
		result3 = await registry.execute_action('test_input', {'index': 5, 'text': 'test input'}, browser_session=browser_session)
		assert result3.extracted_content is not None
		assert 'Input text: test input at index: 5' in result3.extracted_content

	async def test_pydantic_vs_individual_params_consistency(self, registry, browser_session):
		"""Test that pydantic and individual parameter patterns produce consistent results"""

		# Action using individual parameters
		@registry.action('Individual params')
		async def individual_params_action(text: str, number: int, browser_session: BrowserSession):
			return ActionResult(extracted_content=f'Individual: {text}-{number}')

		# Action using pydantic model
		class TestParams(BaseActionModel):
			text: str
			number: int

		@registry.action('Pydantic params', param_model=TestParams)
		async def pydantic_params_action(params: TestParams, browser_session: BrowserSession):
			return ActionResult(extracted_content=f'Pydantic: {params.text}-{params.number}')

		# Both should produce similar results
		test_data = {'text': 'hello', 'number': 42}

		result1 = await registry.execute_action('individual_params_action', test_data, browser_session=browser_session)

		result2 = await registry.execute_action('pydantic_params_action', test_data, browser_session=browser_session)

		# Both should extract the same content (just different prefixes)
		assert result1.extracted_content is not None
		assert 'hello-42' in result1.extracted_content
		assert result2.extracted_content is not None
		assert 'hello-42' in result2.extracted_content
		assert 'Individual:' in result1.extracted_content
		assert 'Pydantic:' in result2.extracted_content
