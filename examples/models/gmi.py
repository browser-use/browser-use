"""
Simple agent run with GMI Cloud.

You need to set GMI_API_KEY in your environment (see https://api.gmi-serving.com/v1/models for the models your key can list).
"""

import asyncio

from dotenv import load_dotenv

from browser_use import Agent, ChatGMI

load_dotenv()

llm = ChatGMI(model='google/gemini-3.6-flash')
agent = Agent(
	task='Find the number of stars of the browser-use repo',
	llm=llm,
)


async def main():
	await agent.run(max_steps=10)


asyncio.run(main())
