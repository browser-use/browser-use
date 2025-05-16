import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from browser_use import Agent

api_key = os.getenv('GROK_API_KEY', '')
if not api_key:
	raise ValueError('GROK_API_KEY is not set')


async def run_search():
	agent = Agent(
		task=(
			'1. Go to https://www.amazon.com'
			'2. Search for "wireless headphones"'
			'3. Filter by "Highest customer rating"'
			'4. Return the title and price of the first product'
		),
		llm=ChatOpenAI(
			base_url='https://api.x.ai/v1',
			model='grok-3-beta',
			api_key=SecretStr(api_key),
		),
		use_vision=False,
	)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(run_search())
