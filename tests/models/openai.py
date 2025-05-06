import asyncio

from langchain_openai import ChatOpenAI
from browser_use import Agent


async def test_openai_model():
	llm = ChatOpenAI(model='gpt-4o')
	agent = Agent(
		task='what is the square root of 4',
		llm=llm,
	)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(test_openai_model())
