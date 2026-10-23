"""
Simple try of the agent.

@dev You need to add REQUESTY_API_KEY to your environment variables.
"""

import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent
from browser_use.llm.requesty.chat import ChatRequesty

load_dotenv()

# Requesty uses provider/model naming, same as OpenRouter.
llm = ChatRequesty(
	model='openai/gpt-4o-mini',
	api_key=os.getenv('REQUESTY_API_KEY'),
)
agent = Agent(
	task='Find the number of stars of the browser-use repo',
	llm=llm,
	use_vision=False,
)


async def main():
	await agent.run(max_steps=10)


asyncio.run(main())
