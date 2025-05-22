"""
Simple try of the agent.

@dev You need to add MODELSCOPE_API_KEY to your environment variables.
"""

import asyncio
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from browser_use import Agent

# dotenv
load_dotenv()

api_key = os.getenv('MODELSCOPE_API_KEY', '')
if not api_key:
	raise ValueError('MODELSCOPE_API_KEY is not set')


async def run_search():
	agent = Agent(
		task=('go to amazon.com, search for laptop'),
		llm=ChatOpenAI(
			base_url='https://api-inference.modelscope.cn/v1/',
			model='Qwen/QwQ-32B-Preview',
			api_key=SecretStr(api_key),
		),
		use_vision=False,
	)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(run_search())
