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

from langchain_openai import AzureChatOpenAI
from pydantic import SecretStr

from browser_use import Agent

# Retrieve Azure-specific environment variables
azure_openai_api_key = os.getenv('AZURE_OPENAI_KEY')
azure_openai_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')

if not azure_openai_api_key or not azure_openai_endpoint:
	raise ValueError('AZURE_OPENAI_KEY or AZURE_OPENAI_ENDPOINT is not set')

# Initialize the Azure OpenAI client
llm = AzureChatOpenAI(
	model='gpt-4o',
	api_key=SecretStr(azure_openai_api_key) if azure_openai_api_key else None,
	azure_endpoint=azure_openai_endpoint,  # Corrected to use azure_endpoint instead of openai_api_base
	api_version='2024-08-01-preview',  # Explicitly set the API version here
)

agent = Agent(
	task='Go to amazon.com, search for laptop, sort by best rating, and give me the price of the first result',
	llm=llm,
	enable_memory=True,
)


async def main():
	await agent.run(max_steps=10)
	input('Press Enter to continue...')


asyncio.run(main())
