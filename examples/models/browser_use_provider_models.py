"""
Point ChatBrowserUse at provider-prefixed models via the Browser Use gateway.

`ChatBrowserUse` isn't limited to the `bu-*` models - it also accepts
provider-prefixed ids:

    - 'anthropic/claude-sonnet-4-6'
    - 'openai/gpt-5.5'
    - 'google/gemini-3-pro'

A single `BROWSER_USE_API_KEY` reaches Claude, GPT, and Gemini without
juggling separate OpenAI / Anthropic / Google keys. For the best speed and
cost, the default `bu-*` models are still recommended.

Setup:
1. Get your API key from https://cloud.browser-use.com/new-api-key
2. Set environment variable: export BROWSER_USE_API_KEY="your-key"
"""

import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent, ChatBrowserUse

load_dotenv()

if not os.getenv('BROWSER_USE_API_KEY'):
	raise ValueError('BROWSER_USE_API_KEY is not set')

# Swap this for any provider-prefixed id the gateway supports, e.g.
#   'openai/gpt-5.5' or 'google/gemini-3-pro'
MODEL = 'anthropic/claude-sonnet-4-6'


async def main():
	agent = Agent(
		task='Find the number of stars of the browser-use repo',
		llm=ChatBrowserUse(model=MODEL),
	)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
