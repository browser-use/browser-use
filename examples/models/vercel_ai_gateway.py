"""
Example using Vercel AI Gateway with browser-use.

Vercel AI Gateway provides an OpenAI-compatible API endpoint that can proxy
requests to various AI providers. This allows you to use Vercel's infrastructure
for rate limiting, caching, and monitoring.

Prerequisites:
1. Set AI_GATEWAY_API_KEY in your environment variables (or rely on VERCEL_OIDC_TOKEN on Vercel)

To see all available models, visit: https://ai-gateway.vercel.sh/v1/models
"""

import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent, ChatVercel

load_dotenv()

api_key = os.getenv('AI_GATEWAY_API_KEY') or os.getenv('VERCEL_OIDC_TOKEN')
if not api_key:
	raise ValueError('AI_GATEWAY_API_KEY or VERCEL_OIDC_TOKEN is not set')

# Basic usage
llm = ChatVercel(
	model='openai/gpt-4o',
	api_key=api_key,
)

# Example with provider options - control which providers are used and in what order
# This will try Vertex AI first, then fall back to Anthropic if Vertex fails
llm_with_provider_options = ChatVercel(
	model='anthropic/claude-sonnet-4.5',
	api_key=api_key,
	provider_options={
		'gateway': {
			'order': ['vertex', 'anthropic'],  # Try Vertex AI first, then Anthropic
		}
	},
)

# Example with reasoning and caching enabled, plus model fallbacks
llm_reasoning_and_fallbacks = ChatVercel(
	model='anthropic/claude-sonnet-4.5',
	api_key=api_key,
	reasoning={
		'anthropic': {'thinking': {'type': 'enabled', 'budgetTokens': 2000}},
	},
	model_fallbacks=[
		'openai/gpt-5.2',
		'google/gemini-2.5-flash',
	],
	caching='auto',
	provider_options={
		'gateway': {
			# Example BYOK configuration; replace with your real keys if needed
			'byok': {
				'anthropic': [
					{
						'apiKey': os.getenv('ANTHROPIC_API_KEY', ''),
					}
				]
			},
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

agent_with_reasoning_and_fallbacks = Agent(
	task='Go to example.com and summarize the main content with detailed reasoning',
	llm=llm_reasoning_and_fallbacks,
)


async def main():
	await agent.run(max_steps=10)
	await agent_with_provider_options.run(max_steps=10)
	await agent_with_reasoning_and_fallbacks.run(max_steps=10)


if __name__ == '__main__':
	asyncio.run(main())
