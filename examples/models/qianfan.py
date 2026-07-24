"""
Simple try of the agent.

@dev You need to add QIANFAN_API_KEY to your environment variables.
"""

import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent, ChatOpenAI

load_dotenv()

api_key = os.getenv('QIANFAN_API_KEY', '')
if not api_key:
	raise ValueError('QIANFAN_API_KEY is not set')

# Browser Use agents rely on structured outputs through OpenAI-compatible response_format.
# Qianfan structured-output smoke tests on 2026-05-16 succeeded with ernie-5.0.


async def run_search():
	agent = Agent(
		task=('go to google, search for browser-use github'),
		llm=ChatOpenAI(
			model='ernie-5.0',
			base_url='https://qianfan.baidubce.com/v2',
			api_key=api_key,
		),
		use_vision=False,
	)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(run_search())
