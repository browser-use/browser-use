from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import Agent

load_dotenv()


async def run_agent(task: str, max_steps: int = 38):
	llm = ChatOpenAI(
		model='gpt-4o',
		temperature=0.0,
	)
	agent = Agent(task=task, llm=llm, use_vision=False)
	result = await agent.run(max_steps=max_steps)
	return result
