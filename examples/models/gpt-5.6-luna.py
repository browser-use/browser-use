"""
Run a browser task with GPT-5.6 Luna or GPT-6 Astra.

@dev You need to add OPENAI_API_KEY to your environment variables.
Set OPENAI_MODEL=gpt-6-astra to run the same task with Astra.
"""

import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent, ChatOpenAI

load_dotenv()

llm = ChatOpenAI(model=os.getenv('OPENAI_MODEL', 'gpt-5.6-luna'))
agent = Agent(
	llm=llm,
	task='Visit https://quotes.toscrape.com/ and list the first three quotes with their authors.',
)


async def main():
	await agent.run(max_steps=20)


asyncio.run(main())
