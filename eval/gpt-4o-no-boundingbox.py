import asyncio

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import Agent, BrowserConfig
from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContextConfig

load_dotenv()


async def run_agent(task: str, max_steps: int = 38):
	browser = Browser(
		config=BrowserConfig(
			new_context_config=BrowserContextConfig(
				highlight_elements=False,
			),
		),
	)
	llm = ChatOpenAI(
		model='gpt-4o',
		temperature=0.0,
	)
	agent = Agent(task=task, llm=llm, browser=browser)
	result = await agent.run(max_steps=max_steps)
	return result


if __name__ == '__main__':
	task = 'Open 1 random Wikipedia pages in new tab'
	result = asyncio.run(run_agent(task))
