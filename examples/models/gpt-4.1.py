"""
Simple try of the agent.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import asyncio

from dotenv import load_dotenv
from lmnr import Laminar

from browser_use import Agent
from browser_use.llm import ChatOpenAI

load_dotenv()


Laminar.initialize()

# All the models are type safe from OpenAI in case you need a list of supported models
llm = ChatOpenAI(model='gpt-4.1-mini')
agent = Agent(
	task='Go to example.com, click on the first link, and give me the title of the page',
	llm=llm,
)


async def main():
	await agent.run(max_steps=10)
	input('Press Enter to continue...')


asyncio.run(main())
