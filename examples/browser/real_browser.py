import os
import sys
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio

import dotenv
from langchain_openai import ChatOpenAI

from browser_use import Agent, Browser, BrowserConfig

dotenv.load_dotenv()

logger = logging.getLogger(__name__)

browser = Browser(
	config=BrowserConfig(
		# NOTE: you need to close your chrome browser - so that this can open your browser in debug mode
		#browser_binary_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
	)
)


async def run_agent():
	agent = Agent(
		task='In docs.google.com write my Papa a quick letter',
		llm=ChatOpenAI(model='gpt-4o'),
		browser=browser,
	)

	await agent.run()
	await browser.close()

	input('Press Enter to close...')


def main():   
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        task = loop.create_task(run_agent())
        loop.run_until_complete(task)

    except KeyboardInterrupt:
        logger.info("Aborted!")
        task.cancel()

    finally:
        loop.close()

if __name__ == '__main__':
	main()
