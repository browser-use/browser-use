"""
Simple browser automation example - edit this file to change what it does!
"""
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

# Load API key from .env file
env_path = Path.home() / '.env'
if env_path.exists():
	load_dotenv(env_path)
else:
	load_dotenv()  # Try current directory

from browser_use import Agent
from langchain_anthropic import ChatAnthropic

# Use Claude Haiku 4.5 - the cheapest and fastest option!
llm = ChatAnthropic(model_name='claude-haiku-4-5-20251001', temperature=0.0)

async def main():
	print('🤖 Starting browser automation...\n')

	# ⭐ CHANGE THIS LINE to make it do different things!
	task = 'Go to google.com and search for cute puppies'

	print(f'Task: {task}\n')

	agent = Agent(
		task=task,
		llm=llm,
	)

	result = await agent.run()

	print('\n✅ Done!')

if __name__ == '__main__':
	asyncio.run(main())
