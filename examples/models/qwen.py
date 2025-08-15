import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


from browser_use import Agent
from browser_use.llm.qwen.chat import ChatQwen

# Initialize the Qwen model
llm = ChatQwen(model='qwen3-235b-a22b')


task = 'Find the founders of browser-use'
agent = Agent(task=task, llm=llm)


async def main():
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
