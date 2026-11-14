"""
Setup:
1. Get your API key from https://cloud.browser-use.com/new-api-key
2. Set environment variable: export BROWSER_USE_API_KEY="your-key"

This example shows how to customize the agent's system prompt to change its behavior.
You can make it more concise, more thorough, or give it a specific persona.
"""

import asyncio
import os
import sys

# Add the parent directory to the path so we can import browser_use
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatBrowserUse


# Custom system prompt - you can make the agent behave however you want
CUSTOM_SYSTEM_PROMPT = """
You are a fast and efficient web assistant. Your rules:
1. Always take the shortest path to complete the task.
2. Never explain your steps unless explicitly asked.
3. Be extremely concise in your final answer.
4. If you can find the answer in 3 steps or less, do it immediately.
5. If you get stuck, try a different approach instead of repeating the same action.
"""


async def main():
	llm = ChatBrowserUse(model='bu-2-0-mini-preview')

	task = "Search for 'best Python web frameworks 2026' and tell me the top 3"

	# Pass the custom system prompt to the agent
	agent = Agent(
		task=task,
		llm=llm,
		system_prompt=CUSTOM_SYSTEM_PROMPT,  # <-- this is the key line
	)

	print("Running agent with custom system prompt...")
	result = await agent.run()
	print("\n=== Final Result ===")
	print(result)


if __name__ == '__main__':
	asyncio.run(main())
