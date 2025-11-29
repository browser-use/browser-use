"""
Example using Vercel AI Gateway with browser-use.

Vercel AI Gateway provides an OpenAI-compatible API endpoint that can proxy
requests to various AI providers. This allows you to use Vercel's infrastructure
for rate limiting, caching, and monitoring.

Prerequisites:
1. Set VERCEL_API_KEY in your environment variables

To see all available models, visit: https://ai-gateway.vercel.sh/v1/models
"""

import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent, ChatVercel

load_dotenv()

api_key = os.getenv('VERCEL_API_KEY')
if not api_key:
	raise ValueError('VERCEL_API_KEY is not set')

# Basic usage
llm = ChatVercel(
	model='openai/gpt-4o',
	api_key=api_key,
)

# Example with provider options - control which providers are used and in what order
# This will try Vertex AI first, then fall back to Anthropic if Vertex fails
llm_with_provider_options = ChatVercel(
	model='anthropic/claude-sonnet-4',
	api_key=api_key,
	provider_options={
		'gateway': {
			'order': ['vertex', 'anthropic']  # Try Vertex AI first, then Anthropic
		}
	},
)

agent = Agent(
	task='Go to example.com and summarize the main content',
	llm=llm,
)

agent_with_provider_options = Agent(
	task='Go to example.com and summarize the main content',
	llm=llm_with_provider_options,
)


async def main():
	await agent.run(max_steps=10)
	await agent_with_provider_options.run(max_steps=10)


if __name__ == '__main__':
	asyncio.run(main())
