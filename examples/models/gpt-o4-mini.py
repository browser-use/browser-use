from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import Agent, Browser

load_dotenv()


async def run_agent(task: str, browser: Browser | None = None, max_steps: int = 38):
	browser = browser or Browser()
	llm = ChatOpenAI(
		model='o4-mini-2025-04-16',
	)
	agent = Agent(task=task, llm=llm, browser=browser)
	result = await agent.run(max_steps=max_steps)
	return result
