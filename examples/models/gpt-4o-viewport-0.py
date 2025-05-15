import asyncio

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import Agent, Browser

load_dotenv()


async def run_agent(task: str, browser: Browser | None = None, max_steps: int = 38):
	browser = browser or Browser()
	llm = ChatOpenAI(
		model='gpt-4o',
		temperature=0.0,
	)
	browser.config.new_context_config.viewport_expansion = 0
	agent = Agent(task=task, llm=llm, browser=browser)
	result = await agent.run(max_steps=max_steps)
	return result


if __name__ == '__main__':
	task = 'Go to https://www.google.com and search for "python" and click on the first result'
	result = asyncio.run(run_agent(task))
	print(result)
