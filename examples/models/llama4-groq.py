import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from lmnr import Laminar

load_dotenv()


Laminar.initialize()


from browser_use import Agent
from browser_use.llm import ChatGroq

groq_api_key = os.environ.get('GROQ_API_KEY')
llm = ChatGroq(
	model='meta-llama/llama-4-maverick-17b-128e-instruct',
	# temperature=0.1,
)

# llm = ChatGroq(
# 	model='meta-llama/llama-4-maverick-17b-128e-instruct',
# 	api_key=os.environ.get('GROQ_API_KEY'),
# 	temperature=0.0,
# )

task = 'Go to amazon.com, search for laptop, sort by best rating, and give me the price of the first result'


async def main():
	agent = Agent(
		task=task,
		llm=llm,
	)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
