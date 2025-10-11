"""
Test ComputerUseAgent (Mode 2) - Full Computer Use integration with function calling loop.

This implements the proper protocol:
1. Model returns function calls
2. Execute actions via computer_use_bridge
3. Send function responses back with screenshot
4. Model continues until task complete
"""

import asyncio

from dotenv import load_dotenv

from browser_use.llm.gemini_computer_use import ChatGeminiComputerUse, ComputerUseAgent

# Load environment variables
load_dotenv('/Users/reagan/Documents/GitHub/browser-use/browser_use/llm/gemini_computer_use/.env')


async def main():
	"""
	Mode 2: Full Computer Use integration with function calling loop.

	This example uses the proper Computer Use protocol:
	- Model returns function calls
	- Execute actions via bridge
	- Send function responses back
	- Continue loop until complete
	"""
	import os

	llm = ChatGeminiComputerUse(
		model='gemini-2.5-computer-use-preview-10-2025',
		api_key=os.getenv('GOOGLE_API_KEY'),  # Load from environment variable
		enable_computer_use=True,
	)

	print(f'✓ Initialized {llm.name} with Computer Use enabled')
	print(f'✓ Provider: {llm.provider}')
	print('✓ Mode: Full Computer Use with function calling loop')
	print()

	# Create ComputerUseAgent
	# IMPORTANT: Don't pass URL in task - let Computer Use handle navigation
	agent = ComputerUseAgent(
		task=("Find the founders of the Browser Use startup"
		),
		llm=llm,
		use_vision=True,
		max_actions_per_step=20,  # Allow multiple actions
	)

	print('🔍 Starting ComputerUseAgent with task...')
	print()

	try:
		# Run the agent
		result = await agent.run()

		print()
		print('=' * 60)
		print('✅ Agent completed successfully!')
		print()
		print('Result:')
		print(result.final_result())  # Use final_result() to get the done message
		print()
		print(f'Number of steps: {len(result.history)}')
		print()

	except Exception as e:
		print()
		print('=' * 60)
		print(f'❌ Error: {e}')
		print()
		import traceback

		traceback.print_exc()


if __name__ == '__main__':
	asyncio.run(main())
