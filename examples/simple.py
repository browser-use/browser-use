import asyncio
import os
import sys

from browser_use.llm.google.chat import ChatGoogle

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from lmnr import Laminar

from browser_use import Agent

Laminar.initialize()


# Initialize the model
# llm = ChatOpenAI(
# 	model='gpt-4.1',
# 	temperature=0.0,
# )
# llm = ChatGroq(
# 	model='meta-llama/llama-4-maverick-17b-128e-instruct',
# )
llm = ChatGoogle(model='models/gemini-2.0-flash')

task = 'Go to kayak.com and find the cheapest one-way flight from Zurich to San Francisco in 3 weeks.'
agent = Agent(task=task, llm=llm)


async def main():
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
