import asyncio

from browser_use import Agent, ChatOpenAI
from browser_use.playwright_recorder import record_playwright_script


async def main():
	print('Starting agent with Playwright recorder...')

	# We use record_playwright_script as an async context manager.
	# It returns a BrowserSession connected to the recorded Chromium instance.
	async with record_playwright_script('recorded_agent_script.py') as browser_session:
		agent = Agent(
			task='Go to github.com and search for browser-use. Then print the top result.',
			llm=ChatOpenAI(model='gpt-4o-mini'),
			browser_session=browser_session,
		)

		await agent.run()

	print('\n✅ Agent finished. Check recorded_agent_script.py for the Playwright code!')


if __name__ == '__main__':
	asyncio.run(main())
