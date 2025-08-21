"""
Simple try of the agent.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import asyncio

from dotenv import load_dotenv
from lmnr import Laminar

from browser_use import Agent, ChatOpenAI

load_dotenv()


Laminar.initialize()

# All the models are type safe from OpenAI in case you need a list of supported models
llm = ChatOpenAI(model='gpt-5-mini')
agent = Agent(
	llm=llm,
	task='Find out which one is cooler: the monkey park or a dolphin tour in Tenerife?',
)


async def main():
	await agent.run(max_steps=20)
	input('Press Enter to continue...')


asyncio.run(main())
