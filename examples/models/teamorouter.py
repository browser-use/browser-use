"""
Simple try of the agent with TeamoRouter.

@dev You need to add TEAMOROUTER_API_KEY to your environment variables.
"""

import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent, ChatAnthropic, ChatOpenAI

load_dotenv()

api_key = os.getenv('TEAMOROUTER_API_KEY', '')
if not api_key:
	raise ValueError('TEAMOROUTER_API_KEY is not set')

# Tag requests so TeamoRouter can attribute traffic to browser-use (optional).
headers = {'X-Client-Source': 'browser-use-teamorouter'}

# TeamoRouter is an OpenAI-compatible API: one key for DeepSeek, Qwen, Kimi, GLM, GPT, Gemini and Claude.
llm = ChatOpenAI(
	model='deepseek-v4-flash',
	base_url='https://api.teamorouter.com/v1',
	api_key=api_key,
	default_headers=headers,
)

# Claude models go through the Anthropic-compatible endpoint instead (note: no /v1 suffix).
claude = ChatAnthropic(
	model='claude-sonnet-4-6',
	base_url='https://api.teamorouter.com',
	api_key=api_key,
	default_headers=headers,
)


async def main():
	# deepseek-v4-flash is text-only, so vision is turned off. Pass llm=claude to use Claude instead.
	agent = Agent(
		task='Go to https://books.toscrape.com and return the title and price of the first book',
		llm=llm,
		use_vision=False,
	)
	await agent.run(max_steps=10)


if __name__ == '__main__':
	asyncio.run(main())
