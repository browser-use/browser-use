import asyncio

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import Agent, BrowserConfig
from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContextConfig

load_dotenv()


async def run_agent(task: str, max_steps: int = 38):
	llm = ChatOpenAI(
		model='gpt-4o',
		temperature=0.0,
	)
	browser = Browser(
		config=BrowserConfig(
			new_context_config=BrowserContextConfig(
				viewport_expansion=0,
			),
		),
	)
	agent = Agent(task=task, llm=llm, browser=browser)
	result = await agent.run(max_steps=max_steps)
	return result


if __name__ == '__main__':
	task = 'Go to https://www.google.com and search for "python" and click on the first result'
	result = asyncio.run(run_agent(task))
	print(result)
