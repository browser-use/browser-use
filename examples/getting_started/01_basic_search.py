"""
Setup:
1. Get your API key from https://cloud.browser-use.com/dashboard/api
2. Set environment variable: export BROWSER_USE_API_KEY="your-key"
"""

import asyncio
import os
import sys

# Add the parent directory to the path so we can import browser_use
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatBrowserUse


async def main():
	llm = ChatBrowserUse()
	task = "We are testing the send_keys function. Go to https://inputtypes.com/ and focus the input box and type 'hello world'. DO NOT use the input_text action. Only use the send_keys action. Mark the task as done right after using the send_keys action."
	agent = Agent(task=task, llm=llm)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
