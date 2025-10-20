"""
Advanced Example

This example demonstrates how to configure the Agent and Browser
with many configuration options, all set to default values.

Check out all configuration settings at https://docs.browser-use.com/customize/agent/all-parameters.
"""

import asyncio

from dotenv import load_dotenv

from browser_use import Agent, Browser, ChatBrowserUse

load_dotenv()


async def main():
	browser = Browser(
		use_cloud=False,
		# headless=False,
		# disable_security=False,
		# extra_chromium_args=[],
		# allowed_domains=None,
		# prohibited_domains=None,
		# cdp_url=None,
	)

	llm = ChatBrowserUse()

	agent = Agent(
		task='Find the number of stars of the browser-use repository on GitHub',
		llm=llm,
		browser=browser,
		# use_vision='auto',
		# save_conversation_path=None,
		# max_failures=3,
		# generate_gif=False,
		# max_actions_per_step=4,
		# use_thinking=True,
		# flash_mode=False,
		# calculate_cost=False,
		# step_timeout=180,
	)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
