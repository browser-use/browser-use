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

# Make sure your deployment exists, double check the region and model name
api_key = os.getenv('AZURE_OPENAI_KEY')
azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
llm = ChatAzureOpenAI(
	model='gpt-4.1-mini',
	api_key=api_key,
	azure_endpoint=azure_endpoint,
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


asyncio.run(main())
