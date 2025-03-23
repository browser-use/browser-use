import os
import sys

from langchain_openai import ChatOpenAI

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio

from browser_use.agent.service import Agent
from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContextConfig
from browser_use.utils import BrowserSessionManager, with_error_handling

llm = ChatOpenAI(model='gpt-4o', temperature=0.0)

@with_error_handling()
async def run_script():
	browser = Browser()
	async with await browser.new_context(
		config=BrowserContextConfig(trace_path='./tmp/traces/')
	) as context:
		agent = Agent(
			task='Go to hackernews, then go to apple.com and return all titles of open tabs',
			llm=llm,
			browser_context=context,
		)
		async with BrowserSessionManager.manage_browser_session(agent) as managed_agent:
			await managed_agent.run()
	await browser.close()

if __name__ == '__main__':
    run_script()
