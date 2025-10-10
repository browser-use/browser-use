"""
Test to verify that gemini-flash-latest and gemini-flash-lite-latest can be looked up correctly.

This test ensures the token cost service correctly handles model names that require
provider prefixes in the LiteLLM pricing data.
"""

import pytest

from browser_use.tokens.service import TokenCost


@pytest.mark.asyncio
async def test_gemini_flash_latest_pricing():
	"""Test that gemini-flash-latest pricing is found"""
	tc = TokenCost(include_cost=True)
	await tc.initialize()
	
	# Test gemini-flash-latest (requires 'gemini/' prefix in pricing data)
	pricing = await tc.get_model_pricing('gemini-flash-latest')
	assert pricing is not None, 'Could not find pricing for gemini-flash-latest'
	assert pricing.model == 'gemini/gemini-flash-latest', f'Expected model key to be "gemini/gemini-flash-latest", got "{pricing.model}"'
	assert pricing.input_cost_per_token is not None, 'Input cost should not be None'
	assert pricing.output_cost_per_token is not None, 'Output cost should not be None'
	assert pricing.input_cost_per_token > 0, 'Input cost should be positive'
	assert pricing.output_cost_per_token > 0, 'Output cost should be positive'


@pytest.mark.asyncio
async def test_gemini_flash_lite_latest_pricing():
	"""Test that gemini-flash-lite-latest pricing is found"""
	tc = TokenCost(include_cost=True)
	await tc.initialize()
	
	# Test gemini-flash-lite-latest (requires 'gemini/' prefix in pricing data)
	pricing = await tc.get_model_pricing('gemini-flash-lite-latest')
	assert pricing is not None, 'Could not find pricing for gemini-flash-lite-latest'
	assert pricing.model == 'gemini/gemini-flash-lite-latest', f'Expected model key to be "gemini/gemini-flash-lite-latest", got "{pricing.model}"'
	assert pricing.input_cost_per_token is not None, 'Input cost should not be None'
	assert pricing.output_cost_per_token is not None, 'Output cost should not be None'


@pytest.mark.asyncio
async def test_regular_gemini_model_pricing():
	"""Test that regular gemini models (without requiring prefix) still work"""
	tc = TokenCost(include_cost=True)
	await tc.initialize()
	
	# Test gemini-2.0-flash (should work without prefix requirement)
	pricing = await tc.get_model_pricing('gemini-2.0-flash')
	assert pricing is not None, 'Could not find pricing for gemini-2.0-flash'
	assert pricing.model == 'gemini-2.0-flash', f'Expected model key to be "gemini-2.0-flash", got "{pricing.model}"'
	assert pricing.input_cost_per_token is not None, 'Input cost should not be None'
	assert pricing.output_cost_per_token is not None, 'Output cost should not be None'