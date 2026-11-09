"""
Simple try of the agent with Runcrate.

@dev You need to add RUNCRATE_API_KEY to your environment variables.
"""

import asyncio

from dotenv import load_dotenv

from browser_use import Agent, ChatRuncrate

load_dotenv()

# Runcrate serves open models through one OpenAI-compatible endpoint.
# The model ids are listed at https://api.runcrate.ai/v1/models; pick one that supports `tools`.
llm = ChatRuncrate(model='deepseek-ai/DeepSeek-V4.1-Flash')
agent = Agent(
	task='Find the number of stars of the browser-use repo',
	llm=llm,
	use_vision=False,
)


async def main():
	await agent.run(max_steps=10)


asyncio.run(main())
