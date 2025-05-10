import asyncio
import os

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from browser_use import Agent


async def test_deepseek_model():
	api_key_deepseek = SecretStr(os.getenv('DEEPSEEK_API_KEY') or '')
	llm = ChatOpenAI(base_url='https://api.deepseek.com/v1', model='deepseek-chat', api_key=SecretStr(api_key_deepseek))

	agent = Agent(
		task='what is the square root of 4',
		llm=llm,
	)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(test_deepseek_model())
