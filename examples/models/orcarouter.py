"""
Simple try of the agent with OrcaRouter.

@dev You need to add ORCAROUTER_API_KEY to your environment variables.
"""

import asyncio

from dotenv import load_dotenv

from browser_use import Agent, ChatOrcaRouter

load_dotenv()

# OrcaRouter is an OpenAI-compatible model gateway routing to 190+ models via one endpoint.
llm = ChatOrcaRouter(model='orcarouter/auto')
agent = Agent(
	task='Find the number of stars of the browser-use repo',
	llm=llm,
	use_vision=False,
)


async def main():
	await agent.run(max_steps=10)


asyncio.run(main())
