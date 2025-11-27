"""Example of using sandbox execution with Browser-Use Agent

This example demonstrates how to use the @sandbox decorator to run
browser automation tasks with the Agent in a sandbox environment.

To run this example:
1. Set your BROWSER_USE_API_KEY environment variable
2. Set your LLM API key (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)
3. Run: python examples/sandbox_execution.py
"""

import asyncio
import os

from browser_use import Browser, ChatBrowserUse, sandbox
from browser_use.agent.service import Agent


# Example with event callbacks to monitor execution
def on_browser_ready(data):
	"""Callback when browser session is created"""
	print('\n🌐 Browser session created!')
	print(f'   Session ID: {data.session_id}')
	print(f'   Live view: {data.live_url}')
	print('   Click the link above to watch the AI agent work!\n')


@sandbox(
	log_level='INFO',
	on_browser_created=on_browser_ready,
	# server_url='http://localhost:8080/sandbox-stream',
	# cloud_profile_id='21182245-590f-4712-8888-9611651a024c',
	# cloud_proxy_country_code='us',
	# cloud_timeout=60,
)
async def pydantic_example(browser: Browser):
	agent = Agent(
		"""go and check my ip address and the location. return the result in json format""",
		browser=browser,
		llm=ChatBrowserUse(),
	)
	res = await agent.run()

	return res.final_result()


async def main():
	"""Run examples"""
	# Check if API keys are set
	if not os.getenv('BROWSER_USE_API_KEY'):
		print('❌ Please set BROWSER_USE_API_KEY environment variable')
		return

	print('\n\n=== Search with AI Agent (with live browser view) ===')

	search_result = await pydantic_example()

	print('\nResults:')
	print(search_result)


if __name__ == '__main__':
	asyncio.run(main())
