import asyncio
import logging
from inspect import signature

import pytest
from pydantic import BaseModel, Field

from browser_use.browser import BrowserSession
from browser_use.controller.registry.service import Registry
from browser_use.controller.registry.views import ActionModel

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


# Test model - renamed to avoid pytest collection warnings
class TestActionParamsModel(ActionModel):
	value: str = Field(description='Test value')


# Our Context type for the Registry - renamed to avoid pytest collection warnings
class TestContextHelper:
	def __init__(self, value):
		self.value = value


@pytest.mark.asyncio
async def test_registry_param_handling():
	"""Test how Registry handles parameter passing for different function signatures."""
	# Create a Registry instance
	registry = Registry[TestContextHelper]()

	# Create test functions with different signatures

	# 1. Function with browser_session as a positional parameter
	@registry.action('Test action with browser_session', param_model=TestActionParamsModel)
	async def action_with_browser_session(params: TestActionParamsModel, browser_session: BrowserSession):
		logger.debug(f'action_with_browser_session called with params={params}, browser_session={browser_session}')
		return {'params': params.model_dump(), 'has_browser': browser_session is not None}

	# 2. Function with browser_session in the model
	class ModelWithBrowserSession(BaseModel):
		value: str
		browser_session: BrowserSession = None

	@registry.action('Test action with browser_session in model')
	async def action_with_browser_in_model(params: ModelWithBrowserSession):
		logger.debug(f'action_with_browser_in_model called with params={params}')
		return {'params': params.model_dump(), 'has_browser': params.browser_session is not None}

	# 3. Function using **kwargs
	@registry.action('Test action with kwargs')
	async def action_with_kwargs(params: TestActionParamsModel, **kwargs):
		logger.debug(f'action_with_kwargs called with params={params}, kwargs={kwargs}')
		return {'params': params.model_dump(), 'kwargs': kwargs}

	# Create a mock browser session
	mock_browser_session = object()  # Just a placeholder

	# Execute the actions
	logger.debug('\n\n=== Testing action_with_browser_session ===')
	result1 = await registry.execute_action(
		'action_with_browser_session', {'value': 'test1'}, browser_session=mock_browser_session
	)
	logger.debug(f'Result: {result1}')

	logger.debug('\n\n=== Testing action_with_browser_in_model ===')
	result2 = await registry.execute_action(
		'action_with_browser_in_model',
		{'value': 'test2', 'browser_session': None},  # Browser session in model is None
		browser_session=mock_browser_session,  # Browser session in execute_action is provided
	)
	logger.debug(f'Result: {result2}')

	logger.debug('\n\n=== Testing action_with_kwargs ===')
	result3 = await registry.execute_action('action_with_kwargs', {'value': 'test3'}, browser_session=mock_browser_session)
	logger.debug(f'Result: {result3}')

	# Print all signatures
	logger.debug('\n\n=== Function Signatures ===')
	logger.debug(f'action_with_browser_session: {signature(action_with_browser_session)}')
	logger.debug(f'action_with_browser_in_model: {signature(action_with_browser_in_model)}')
	logger.debug(f'action_with_kwargs: {signature(action_with_kwargs)}')

	return result1, result2, result3


if __name__ == '__main__':
	# Run the test
	asyncio.run(test_registry_param_handling())
