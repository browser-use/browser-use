import asyncio

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import Agent

load_dotenv()


async def run_hover():
	llm = ChatOpenAI(model='gpt-4o')
	agent = Agent(
		task='Go to "https://en.wikipedia.org/wiki/Main_Page", hover over Wikipedia link in the middle and change '
		'the page preview setting.',
		llm=llm,
		max_actions_per_step=1,
		use_vision=True,
	)
	await agent.run(max_steps=5)


if __name__ == '__main__':
	asyncio.run(run_hover())
