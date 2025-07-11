"""
Simple try of the agent.

@dev You need to add NOVITA_API_KEY to your environment variables.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()


from browser_use import Agent
from browser_use.llm import ChatDeepSeek

api_key = os.getenv('OPENAI_API_KEY', '')
if not api_key:
	raise ValueError('OPENAI_API_KEY is not set')


async def run_search():
	agent = Agent(
		task='Go to example.com, click on the first link, and give me the title of the page',
		llm=ChatDeepSeek(
			base_url='https://api.deepseek.com/v1',
			model='deepseek-chat',
			api_key=api_key
		),
		
		use_vision=False,
	)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(run_search())
