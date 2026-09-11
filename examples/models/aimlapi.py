"""
Simple try of the agent with aimlapi.com.

@dev You need to add AIMLAPI_API_KEY to your environment variables.
"""

import asyncio

from dotenv import load_dotenv

from browser_use import Agent, ChatAIMLAPI

load_dotenv()

# aimlapi.com is an OpenAI-compatible gateway routing to 350+ chat models via one endpoint.
# Pick any id from https://api.aimlapi.com/v1/models that reports the `structured_output`
# capability - browser-use drives the agent through JSON-schema structured output.
llm = ChatAIMLAPI(model='anthropic/claude-sonnet-4.6')
agent = Agent(
	task='Find the number of stars of the browser-use repo',
	llm=llm,
	use_vision=False,
)


async def main():
	await agent.run(max_steps=10)


asyncio.run(main())
