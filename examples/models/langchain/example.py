"""
Example of using LangChain models with browser-use.

This example demonstrates how to:
1. Wrap a LangChain model with ChatLangchain
2. Use it with a browser-use Agent
3. Run a simple web automation task

@file purpose: Example usage of LangChain integration with browser-use
"""

import asyncio

from langchain_openai import ChatOpenAI  # pyright: ignore
from lmnr import Laminar

from browser_use import Agent
from examples.models.langchain.chat import ChatLangchain

Laminar.initialize()


async def main():
	"""Basic example using ChatLangchain with OpenAI through LangChain."""

	# Create a LangChain model (OpenAI)
	langchain_model = ChatOpenAI(
		model='gpt-4o-mini',
		temperature=0.1,
	)

	# Wrap it with ChatLangchain to make it compatible with browser-use
	llm = ChatLangchain(chat=langchain_model)

	# Create a simple task
	task = "Go to google.com and search for 'browser automation with Python'"

	# Create and run the agent
	agent = Agent(
		task=task,
		llm=llm,
	)

	print(f'🚀 Starting task: {task}')
	print(f'🤖 Using model: {llm.name} (provider: {llm.provider})')

	# Run the agent
	history = await agent.run()

	print(f'✅ Task completed! Steps taken: {len(history.history)}')

	# Print the final result if available
	if history.final_result():
		print(f'📋 Final result: {history.final_result()}')

		return history


if __name__ == '__main__':
	print('🌐 Browser-use LangChain Integration Example')
	print('=' * 45)

	asyncio.run(main())
