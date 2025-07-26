"""
Getting Started Example 1: Basic Search

This example demonstrates the most basic browser-use functionality:
- Navigate to a website
- Perform a search
- Get results

Perfect for first-time users to understand how browser-use works.
"""

import asyncio
import os
import sys

# Add the parent directory to the path so we can import browser_use
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.llm.openai.chat import ChatOpenAI


async def main():
	# Initialize the model
	llm = ChatOpenAI(model='gpt-4o-mini')

	# Define a simple search task
	task = "Search Google for 'what is browser automation' and tell me the top 3 results"

	# Create and run the agent
	agent = Agent(task=task, llm=llm)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
