import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

from browser_use import Agent

load_dotenv()


async def run_search():
	agent = Agent(
		# llm=llm,
		task='How many stars does the browser-use repo have?',
		flash_mode=True,
		skills=['502af156-2a75-4b4e-816d-b2dc138b6647'],  # skill for fetching the number of stars of any Github repository
	)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(run_search())
