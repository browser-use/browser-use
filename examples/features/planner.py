import asyncio
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from browser_use import Agent

load_dotenv()
api_key = os.getenv('DEEPSEEK_API_KEY', '')
if not api_key:
	raise ValueError('DEEPSEEK_API_KEY is not set')


llm = ChatOpenAI(model='gpt-4o', temperature=0.0)
planner_llm = ChatOpenAI(
	model='o3-mini',
)
task = 'your task'


agent = Agent(task=task, llm=llm, planner_llm=planner_llm, use_vision_for_planner=False, planner_interval=1)


async def main():
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
