"""
Simple try of the agent.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import asyncio
import os

from dotenv import load_dotenv
from lmnr import Laminar

from browser_use import Agent, ChatOpenAI

load_dotenv()


Laminar.initialize()

# All the models are type safe from OpenAI in case you need a list of supported models
llm = ChatOpenAI(
	model='x-ai/grok-4',
	base_url='https://openrouter.ai/api/v1',
	api_key=os.getenv('OPENROUTER_API_KEY'),
)
agent = Agent(
	task='Go to example.com, click on the first link, and give me the title of the page',
	llm=llm,
)


async def main():
	await agent.run(max_steps=10)
	input('Press Enter to continue...')


asyncio.run(main())
