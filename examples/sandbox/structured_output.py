"""Example of using structured output with sandbox execution

To run:
    export BROWSER_USE_API_KEY=your_key
    python examples/sandbox/structured_output.py
"""

import asyncio
import os

from pydantic import BaseModel, Field

from browser_use import Agent, Browser, ChatBrowserUse, sandbox
from browser_use.agent.views import AgentHistoryList


class IPLocation(BaseModel):
	"""Structured output for IP location data"""

	ip_address: str = Field(description='The public IP address')
	country: str = Field(description='Country name')
	city: str | None = Field(default=None, description='City name if available')
	region: str | None = Field(default=None, description='Region/state if available')


@sandbox(log_level='INFO')
async def get_ip_location(browser: Browser) -> AgentHistoryList:
	"""Get IP location using sandbox"""
	agent = Agent(
		task='Go to ipinfo.io and extract my IP address and location details (country, city, region)',
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

	result = await get_ip_location()
	location = result.get_structured_output(IPLocation)

	if location:
		print(f'IP: {location.ip_address}')
		print(f'Country: {location.country}')
		print(f'City: {location.city or "N/A"}')
		print(f'Region: {location.region or "N/A"}')
	else:
		print(f'No structured output. Final result: {result.final_result()}')


if __name__ == '__main__':
	asyncio.run(main())
