import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio

from langchain_openai import ChatOpenAI

from browser_use.agent.service import Agent
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContextConfig
from browser_use.utils import BrowserSessionManager, with_error_handling

browser = Browser(
	config=BrowserConfig(
		disable_security=True,
		headless=False,
		new_context_config=BrowserContextConfig(save_recording_path='./tmp/recordings'),
	)
)
llm = ChatOpenAI(model='gpt-4o')


@with_error_handling()
async def run_script():
    agents = [
        Agent(task=task, llm=llm, browser=browser)
        for task in [
            'Search Google for weather in Tokyo',
            'Check Reddit front page title',
            'Look up Bitcoin price on Coinbase',
            'Find NASA image of the day',
        ]
    ]

    agentX = Agent(
        task='Go to apple.com and return the title of the page',
        llm=llm,
        browser=browser,
    )

    async with BrowserSessionManager.manage_browser_session(agentX) as managed_agent:
        await asyncio.gather(*[agent.run() for agent in agents])
        await managed_agent.run()

if __name__ == '__main__':
    run_script()
