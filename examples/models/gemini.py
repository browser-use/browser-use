import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

from browser_use import Agent, ChatGoogle

load_dotenv()

api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
	raise ValueError('GOOGLE_API_KEY is not set')

llm = ChatGoogle(model='gemini-2.5-flash', api_key=api_key, temperature=0.0)


async def run_search():
	agent = Agent(
		task='search on amazon for laptop and find the latest review ',
		llm=llm,
	)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(run_search())
