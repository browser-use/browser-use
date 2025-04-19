import asyncio
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import Agent
from browser_use.controller.service import Controller

load_dotenv()
if not os.getenv('OPENAI_API_KEY'):
	raise ValueError('OPENAI_API_KEY is not set. Please add it to your environment variables.')


async def run_number_input():
	llm = ChatOpenAI(model='gpt-4o')
	agent = Agent(
		# for demonstration purposes, to make sure number actions is selected
		controller=Controller(exclude_actions=['input_text']),
		task='Go to https://tools.usps.com/zip-code-lookup.htm?citybyzipcode and find city covered by zip code 94107.',
		llm=llm,
		max_actions_per_step=1,
		use_vision=True,
	)
	await agent.run(max_steps=5)


if __name__ == '__main__':
	asyncio.run(run_number_input())
