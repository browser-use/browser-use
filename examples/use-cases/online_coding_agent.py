# Goal: Implements a multi-agent system for online code editors, with separate agents for coding and execution.

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.browser import BrowserSession
from browser_use.llm import ChatOpenAI

if not os.getenv('OPENAI_API_KEY'):
	raise ValueError('OPENAI_API_KEY is not set. Please add it to your environment variables.')


async def main():
	browser_session = BrowserSession()
	model = ChatOpenAI(model='gpt-4o')

	# Initialize browser agent
	agent1 = Agent(
		task='Open an online code editor programiz.',
		llm=model,
		browser_session=browser_session,
	)
	executor = Agent(
		task='Executor. Execute the code written by the coder and suggest some updates if there are errors.',
		llm=model,
		browser_session=browser_session,
	)

	coder = Agent(
		task='Coder. Your job is to write and complete code. You are an expert coder. Code a simple calculator. Write the code on the coding interface after agent1 has opened the link.',
		llm=model,
		browser_session=browser_session,
	)
	await agent1.run()
	await executor.run()
	await coder.run()


if __name__ == '__main__':
	asyncio.run(main())
