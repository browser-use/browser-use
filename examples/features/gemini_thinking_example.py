"""
Example of using Gemini 2.5 Flash models with thinking budget.

This example demonstrates how to control internal reasoning tokens for Gemini 2.5 Flash models.

For CLI usage, configure thinking budget in your config.json file at ~/.config/browseruse/config.json:
{
  "model": {
    "name": "gemini-2.5-flash-preview-04-17",
    "thinking_budget": 1024,
    "temperature": 0.0
  }
}
"""

import asyncio

from langchain_google_genai import ChatGoogleGenerativeAI

from browser_use import Agent


async def main():
	# Example 1: Enable thinking for complex reasoning tasks
	llm_with_thinking = ChatGoogleGenerativeAI(
		model='gemini-2.5-flash-preview-04-17',
		thinking_budget=2048,  # Allow up to 2048 thinking tokens
	)

	complex_agent = Agent(
		task='Go to a news website and analyze the sentiment of the top 3 headlines, explaining your reasoning',
		llm=llm_with_thinking,
	)

	await complex_agent.run()

	# Example 2: Disable thinking for simple tasks (faster responses)
	llm_fast = ChatGoogleGenerativeAI(
		model='gemini-2.5-flash-preview-04-17',
		thinking_budget=0,  # Disable thinking completely
	)

	fast_agent = Agent(task="Navigate to google.com and search for 'weather'", llm=llm_fast)

	await fast_agent.run()

	# Example 3: Adaptive mode (let the model decide)
	llm_adaptive = ChatGoogleGenerativeAI(
		model='gemini-2.5-flash-preview-04-17',
		thinking_budget=None,  # Model decides thinking budget automatically
	)

	adaptive_agent = Agent(task='Find a recipe for chocolate cake and list the ingredients', llm=llm_adaptive)

	await adaptive_agent.run()


if __name__ == '__main__':
	asyncio.run(main())
