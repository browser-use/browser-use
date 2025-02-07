"""
Simple try of the agent.

@dev You need to add AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT to your environment variables.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

from langchain_openai import AzureChatOpenAI

from browser_use import Agent

# Retrieve Azure-specific environment variables
azure_openai_api_key = os.environ.get('AZURE_OPENAI_API_KEY')
azure_openai_endpoint = os.environ.get('AZURE_OPENAI_ENDPOINT')

# Initialize the Azure OpenAI client
llm = AzureChatOpenAI(
    model_name='gpt-4o', 
    openai_api_key=azure_openai_api_key,
    azure_endpoint=azure_openai_endpoint,  # Corrected to use azure_endpoint instead of openai_api_base
    deployment_name='gpt-4o',  # Use deployment_name for Azure models
    api_version='2024-08-01-preview'  # Explicitly set the API version here
)

agent = Agent(
    task='Go to amazon.com, search for laptop, sort by best rating, and give me the price of the first result',
    llm=llm,
)


async def main():
    await agent.run(max_steps=10)
    input('Press Enter to continue...')


asyncio.run(main())