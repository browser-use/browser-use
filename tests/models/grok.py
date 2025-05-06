import asyncio
import os

from langchain_openai import ChatOpenAI
from browser_use import Agent
from pydantic import SecretStr


async def test_grok_model():
    api_key_grok = SecretStr(os.getenv('GROK_API_KEY') or '')
    llm = ChatOpenAI(
        base_url='https://api.x.ai/v1',
        model='grok-3-beta',
        api_key=SecretStr(api_key_grok)
    )
	
    agent = Agent(
		task='what is the square root of 4',
		llm=llm,
	)
	
    await agent.run()


if __name__ == '__main__':
	asyncio.run(test_grok_model())
