"""
Simple try of the agent.

@dev You need to add MODELSCOPE_API_KEY to your environment variables.
"""

import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent, ChatOpenAI

# dotenv
load_dotenv()

api_key = os.getenv('MODELSCOPE_API_KEY', '')
if not api_key:
	raise ValueError('MODELSCOPE_API_KEY is not set')


async def run_search():
	agent = Agent(
		# task=('go to amazon.com, search for laptop'),
		task=('go to google, search for modelscope'),
		llm=ChatOpenAI(base_url='https://api-inference.modelscope.cn/v1/', model='Qwen/Qwen2.5-VL-72B-Instruct', api_key=api_key),
		use_vision=False,
	)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(run_search())
