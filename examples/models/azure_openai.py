"""
Simple try of the agent.

@dev You need to add AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT to your environment variables.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()


from browser_use import Agent
from browser_use.llm import ChatAzureOpenAI

# Initialize the Azure OpenAI client
llm = ChatAzureOpenAI(
	model='o4-mini',
)

TASK = """
Go to google.com/travel/flights and find the cheapest flight from New York to Paris on 2025-10-15
"""

agent = Agent(
	task=TASK,
	llm=llm,
)


async def main():
	await agent.run(max_steps=10)
	input('Press Enter to continue...')


asyncio.run(main())
