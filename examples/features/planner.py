import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.llm import ChatOpenAI

llm = ChatOpenAI(model='gpt-4.1', temperature=0.0)
planner_llm = ChatOpenAI(
	model='o3-mini',
)
task = 'your task'


agent = Agent(task=task, llm=llm, planner_llm=planner_llm, use_vision_for_planner=False, planner_interval=1)


async def main():
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
