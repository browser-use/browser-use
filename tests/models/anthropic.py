import asyncio
import os

from langchain_anthropic import ChatAnthropic
from browser_use import Agent
from pydantic import SecretStr


async def test_anthropic_model():
    api_key_anthropic = SecretStr(os.getenv('ANTHROPIC_API_KEY') or '')

    llm = ChatAnthropic(
		model_name='claude-3-5-sonnet-20240620',
		timeout=100,
		temperature=0.0,
		stop=None,
		api_key=api_key_anthropic,
	)
	
    agent = Agent(
		task='what is the square root of 4',
		llm=llm,
	)
	
    await agent.run()


if __name__ == '__main__':
	asyncio.run(test_anthropic_model())
