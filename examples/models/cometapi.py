"""
Simple try of the agent.

@dev You need to add COMETAPI_KEY to your environment variables.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()


from browser_use import Agent, ChatOpenAI

api_key = os.getenv('COMETAPI_KEY', '')
if not api_key:
	raise ValueError('COMETAPI_KEY is not set')


async def run_search():
	agent = Agent(
		task=(
			'1. Go to https://www.reddit.com/r/LocalLLaMA '
			"2. Search for 'browser use' in the search bar"
			'3. Click on first result'
			'4. Return the first comment'
		),
		llm=ChatOpenAI(
			base_url='https://api.cometapi.com/v1/',
			model='gpt-4o-mini',
			api_key=api_key,
		),
		use_vision=False,
	)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(run_search())
