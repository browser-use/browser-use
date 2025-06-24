import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


from browser_use import Agent
from browser_use.llm import ChatGroq

groq_api_key = os.environ.get('GROQ_API_KEY')
llm = ChatGroq(
	model='meta-llama/llama-4-maverick-17b-128e-instruct',
	temperature=0.0,
)

# llm = ChatGroq(
# 	model='meta-llama/llama-4-maverick-17b-128e-instruct',
# 	api_key=os.environ.get('GROQ_API_KEY'),
# 	temperature=0.0,
# )

task = 'Find the founders of browser-use'


async def main():
	agent = Agent(
		task=task,
		llm=llm,
	)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
