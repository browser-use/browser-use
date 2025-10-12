import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, Browser, ChatGoogle

# Connect to your existing Chrome browser
browser = Browser(
	executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
	user_data_dir='~/Library/Application Support/Google/Chrome',
	profile_directory='Default',
)


async def main():
	# save storage state
	agent = Agent(
		llm=ChatGoogle(model='gemini-flash-latest'),
		# Google blocks this approach, so we use a different search engine
		task='go to amazon.com and buy pens to draw on the whiteboard',
		browser=browser,
	)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
