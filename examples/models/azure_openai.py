"""
Simple try of the agent with Azure OpenAI.

@dev You need to add AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT to your environment variables.

For GPT-5.1 Codex models (gpt-5.1-codex-mini, etc.), use:
    llm = ChatAzureOpenAI(
        model='gpt-5.1-codex-mini',
        api_version='2025-03-01-preview',  # Required for Responses API
        # use_responses_api='auto',  # Default: auto-detects based on model
    )

The Responses API is automatically used for models that require it.
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
	model='gpt-5.1-codex-mini', api_key=api_key, azure_endpoint=azure_endpoint, api_version='2025-03-01-preview'
)

TASK = """
Go to google.com/travel/flights and find the cheapest flight from New York to Paris on next Sunday
"""

agent = Agent(
	task=TASK,
	llm=llm,
)


async def main():
	await agent.run(max_steps=25)


asyncio.run(main())
