"""Simple test to trace Computer Use flow"""

import asyncio
import logging

from dotenv import load_dotenv

from browser_use.llm.gemini_computer_use import ChatGeminiComputerUse, ComputerUseAgent

# Load environment variables
load_dotenv('/Users/reagan/Documents/GitHub/browser-use/browser_use/llm/gemini_computer_use/.env')

# Set up detailed logging
logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


async def main():
	"""Test Computer Use with simple task"""
	import os

	llm = ChatGeminiComputerUse(
		model='gemini-2.5-computer-use-preview-10-2025',
		api_key=os.getenv('GOOGLE_API_KEY'),  # Load from environment variable
		enable_computer_use=True,
	)

	print('✓ LLM initialized')

	agent = ComputerUseAgent(
		task="Open a web browser, navigate to news.ycombinator.com, use get_browser_state() to find the top article title, then call done() with the title.",
		llm=llm,
		use_vision=True,
		max_actions_per_step=20,
	)

	print('✓ Agent initialized')
	print('🔍 Starting agent...\n')

	try:
		result = await agent.run()
		print('\n✅ Success!')
		print(f'Result: {result}')
	except Exception as e:
		print(f'\n❌ Error: {e}')
		import traceback
		traceback.print_exc()


if __name__ == '__main__':
	asyncio.run(main())
