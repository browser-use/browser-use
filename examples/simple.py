import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatOpenAI


async def main():
	# Choose your model
	llm = ChatOpenAI(model='gpt-5-mini')

	# Define your task
	task = 'Go and find the founders of browser-use'

	# Create the agent
	agent = Agent(task=task, llm=llm)

	# Start
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
