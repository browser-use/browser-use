"""
Example of using n1n.ai with browser-use.

n1n.ai provides access to 400+ LLM models through a unified OpenAI-compatible API.
This makes it easy to switch between different models (OpenAI, Anthropic, Gemini,
Llama, and many more) without managing multiple API keys.

To use this example:
1. Get your API key from https://n1n.ai/console
2. Set N1N_API_KEY environment variable
3. Run this script

Features:
- Single API key for 400+ models
- Competitive pricing (some models up to 1/10 of official price)
- Unified billing
- Easy model switching
"""

import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent, ChatN1n

load_dotenv()


async def main():
	# Get API key from environment
	api_key = os.getenv('N1N_API_KEY')
	if not api_key:
		raise ValueError('Please set N1N_API_KEY environment variable. Get your key from https://n1n.ai/console')

	# Option 1: Use ChatN1n directly (recommended)
	# You can use any model available through n1n.ai
	# Examples: gpt-4o, claude-3-5-sonnet, gemini-2.0-flash-exp, llama-3.1-70b, etc.
	llm = ChatN1n(
		model='gpt-4o',  # or any model available through n1n.ai
		api_key=api_key,
		temperature=0.2,
	)

	# Option 2: Use the factory function
	# from browser_use.llm.models import get_llm_by_name
	# llm = get_llm_by_name('n1n_gpt-4o')  # Uses N1N_API_KEY from environment

	# Create and run the agent
	task = 'Go to example.com, click on the first link, and give me the title of the page'
	agent = Agent(
		task=task,
		llm=llm,
	)

	print(f'Running task with n1n.ai model {llm.name}: {task}')
	history = await agent.run(max_steps=10)
	result = history.final_result()

	print(f'Result: {result}')


if __name__ == '__main__':
	asyncio.run(main())
