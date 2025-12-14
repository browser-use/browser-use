"""Example of using structured output with sandbox execution

This example demonstrates how to get typed Pydantic output from sandbox:
1. Using return type annotation AgentHistoryList[MyModel] - structured_output property works automatically
2. Using get_structured_output(MyModel) method - works even without type annotation

To run:
    export BROWSER_USE_API_KEY=your_key
    python examples/sandbox/structured_output.py
"""

import asyncio
import os

from pydantic import BaseModel, Field

from browser_use import Agent, Browser, ChatBrowserUse, sandbox
from browser_use.agent.views import AgentHistoryList


# Define structured output schema
class IPLocation(BaseModel):
	"""Structured output for IP location data"""

	ip_address: str = Field(description='The public IP address')
	country: str = Field(description='Country name')
	city: str | None = Field(default=None, description='City name if available')
	region: str | None = Field(default=None, description='Region/state if available')


# Method 1: Return type annotation with generic parameter
# The structured_output property will work automatically
@sandbox(log_level='INFO')
async def get_ip_with_type_hint(browser: Browser) -> AgentHistoryList[IPLocation]:
	"""Sandbox function with typed return - structured_output works automatically"""
	agent = Agent(
		task='Go to ipinfo.io and extract my IP address and location details (country, city, region)',
		browser=browser,
		llm=ChatBrowserUse(),
		output_model_schema=IPLocation,
	)
	return await agent.run(max_steps=10)


# Method 2: Return type without generic parameter
# Use get_structured_output(schema) method instead
@sandbox(log_level='INFO')
async def get_ip_without_generic(browser: Browser) -> AgentHistoryList:
	"""Sandbox function with non-generic return type - use get_structured_output() method"""
	agent = Agent(
		task='Search DuckDuckGo for "what is my ip" and extract the IP address and location shown in results',
		browser=browser,
		llm=ChatBrowserUse(),
		output_model_schema=IPLocation,
	)
	return await agent.run(max_steps=10)


async def main():
	if not os.getenv('BROWSER_USE_API_KEY'):
		print('❌ Please set BROWSER_USE_API_KEY environment variable')
		print('   Get a key at: https://cloud.browser-use.com/new-api-key')
		return

	print('=' * 60)
	print('Sandbox Structured Output Example')
	print('=' * 60)

	# Example 1: With type hint - structured_output property works
	print('\n📍 Method 1: Using return type annotation')
	print('   Return type: AgentHistoryList[IPLocation]')
	print('   Access via: result.structured_output')
	print('-' * 60)

	result1 = await get_ip_with_type_hint()

	# structured_output property works because return type was annotated
	location1 = result1.structured_output
	if location1:
		print('\n✅ Got structured output via property:')
		print(f'   IP Address: {location1.ip_address}')
		print(f'   Country: {location1.country}')
		print(f'   City: {location1.city or "N/A"}')
		print(f'   Region: {location1.region or "N/A"}')
	else:
		print('❌ No structured output (check if task completed successfully)')
		print(f'   Final result: {result1.final_result()}')

	# Example 2: Without generic type parameter - use get_structured_output method
	print('\n' + '=' * 60)
	print('\n📍 Method 2: Using get_structured_output() method')
	print('   Return type: AgentHistoryList (no generic parameter)')
	print('   Access via: result.get_structured_output(IPLocation)')
	print('-' * 60)

	result2 = await get_ip_without_generic()

	# structured_output property returns None (no generic type parameter)
	assert result2.structured_output is None, 'Expected None without generic type parameter'
	print('\n   result.structured_output is None (expected - no generic param)')

	# But get_structured_output with explicit schema works
	location2 = result2.get_structured_output(IPLocation)
	if location2:
		print('\n✅ Got structured output via method:')
		print(f'   IP Address: {location2.ip_address}')
		print(f'   Country: {location2.country}')
		print(f'   City: {location2.city or "N/A"}')
		print(f'   Region: {location2.region or "N/A"}')
	else:
		print('❌ No structured output (check if task completed successfully)')
		print(f'   Final result: {result2.final_result()}')

	print('\n' + '=' * 60)
	print('Done!')


if __name__ == '__main__':
	asyncio.run(main())
