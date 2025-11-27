import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.llm import ChatGroq

try:
	from lmnr import Laminar

	Laminar.initialize()
except ImportError:
	pass

llm = ChatGroq(model='openai/gpt-oss-20b', include_action_descriptions=True)

task = 'Go to amazon.com, search for laptop, sort by best rating, and give me the price of the first result'


async def main():
	agent = Agent(
		task=task,
		llm=llm,
		use_vision=False,
		use_judge=False,
	)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
