"""
Use Eden AI (an EU-based, OpenAI-compatible LLM gateway) with browser-use.

@dev You need to add EDENAI_API_KEY to your environment variables.
Get a key at https://www.edenai.co
"""

import asyncio

from browser_use import Agent
from browser_use.llm import ChatEdenAI

# Eden AI model ids are vendor-prefixed, e.g. 'openai/gpt-4o-mini',
# 'anthropic/claude-sonnet-4-5' or 'mistral/mistral-large-latest'.
# ChatEdenAI reads EDENAI_API_KEY and defaults to https://api.edenai.run/v3
# (set base_url='https://api.eu.edenai.run/v3' for EU data residency).
llm = ChatEdenAI(model='openai/gpt-4o-mini')

agent = Agent(
	task='Find the number of stars of the browser-use repo',
	llm=llm,
	use_vision=False,
)


async def main():
	await agent.run(max_steps=10)


asyncio.run(main())
