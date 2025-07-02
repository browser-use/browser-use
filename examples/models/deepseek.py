import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_deepseek import ChatDeepSeek
from pydantic import SecretStr

from browser_use import Agent

import lucidicai as lai

api_key = os.getenv('DEEPSEEK_API_KEY', '')
if not api_key:
	raise ValueError('DEEPSEEK_API_KEY is not set')

lai.init("Reddit Search")

async def run_search():
	agent = Agent(
		task=(
			'1. Go to https://www.reddit.com/r/LocalLLaMA '
			"2. Search for 'browser use' in the search bar"
			'3. Click on first result'
			'4. Return the first comment'
		),
		llm=ChatDeepSeek(
			base_url='https://api.deepseek.com/v1',
			model='deepseek-chat',
			api_key=SecretStr(api_key),
		),
		use_vision=False,
	)
	handler = lai.LucidicLangchainHandler()
	handler.attach_to_llms(agent)

	await agent.run()

	lai.end_session()


if __name__ == '__main__':
	asyncio.run(run_search())
