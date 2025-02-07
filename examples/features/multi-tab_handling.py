"""
Simple try of the agent.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

from langchain_openai import ChatOpenAI

from browser_use import Agent

api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    raise ValueError("OPENAI_API_KEY is not set.")

# video: https://preview.screen.studio/share/clenCmS6
llm = ChatOpenAI(model='gpt-4o')
agent = Agent(
	task='open 2 tabs with virat kohli and sachin tendulkar, then go back to the first and stop',
	llm=llm,
)


async def main():
	await agent.run()


asyncio.run(main())