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
from browser_use.llm import ChatOpenAI

import lucidicai as lai

api_key = os.getenv('NOVITA_API_KEY', '')
if not api_key:
	raise ValueError('NOVITA_API_KEY is not set')

lai.init("Reddit search")

async def run_search():
	agent = Agent(
		task=(
			'1. Go to https://www.reddit.com/r/LocalLLaMA '
			"2. Search for 'browser use' in the search bar"
			'3. Click on first result'
			'4. Return the first comment'
		),
		llm=ChatOpenAI(
			base_url='https://api.novita.ai/v3/openai',
			model='deepseek/deepseek-v3-0324',
			api_key=api_key,
		),
		use_vision=False,
	)
	handler = lai.LucidicLangchainHandler()
	handler.attach_to_llms(agent)

	await agent.run()

	lai.end_session()


if __name__ == '__main__':
	asyncio.run(run_search())
