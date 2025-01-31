import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import Agent, Controller, Browser, BrowserConfig

load_dotenv()

browser = Browser(config=BrowserConfig(headless=False))
controller = Controller()


async def main():
    task = 'Prompt the user for input and display a notification with the input.'
    model = ChatOpenAI(model='gpt-4o')
    agent = Agent(task=task, llm=model, controller=controller, browser=browser)

    await agent.run()
    await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
