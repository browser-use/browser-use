import asyncio
import os

from langchain_openai import AzureChatOpenAI
from browser_use import Agent
from pydantic import SecretStr


async def test_azure_model():
    llm = AzureChatOpenAI(
			model='gpt-4o',
			api_version='2024-10-21',
			azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT', ''),
			api_key=SecretStr(os.getenv('AZURE_OPENAI_KEY', '')),
	)
	
    agent = Agent(
		task='what is the square root of 4',
		llm=llm,
	)
	
    await agent.run()


if __name__ == '__main__':
	asyncio.run(test_azure_model())
