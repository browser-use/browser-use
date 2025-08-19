import asyncio
import os
import sys

from browser_use.llm.openai.chat import ChatOpenAI

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent

llm = ChatOpenAI(model='o4-mini')


task = (
	'Find current stock price of companies Meta and Amazon. Then, make me a CSV file with 2 columns: company name, stock price.'
)

agent = Agent(task=task, llm=llm)


async def main():
	import time

	start_time = time.time()
	history = await agent.run()
	# token usage
	print(history.usage)
	end_time = time.time()
	print(f'Time taken: {end_time - start_time} seconds')


if __name__ == '__main__':
	asyncio.run(main())
