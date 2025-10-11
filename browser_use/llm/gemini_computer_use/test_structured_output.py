"""Test that structured_output contains the done message from Computer Use"""

import asyncio

from dotenv import load_dotenv

from browser_use.llm.gemini_computer_use import ChatGeminiComputerUse, ComputerUseAgent

# Load environment variables
load_dotenv('/Users/reagan/Documents/GitHub/browser-use/browser_use/llm/gemini_computer_use/.env')


async def main():
	"""Test structured_output captures done message"""
	import os

	llm = ChatGeminiComputerUse(
		model='gemini-2.5-computer-use-preview-10-2025',
		api_key=os.getenv('GOOGLE_API_KEY'),  # Load from environment variable
		enable_computer_use=True,
	)

	print('✓ LLM initialized')

	# Use a very simple task that should complete quickly
	agent = ComputerUseAgent(
		task="Open a web browser, then immediately call done() with the message 'Browser opened successfully'",
		llm=llm,
		use_vision=True,
		max_actions_per_step=20,
		max_steps=3,  # Limit steps to avoid timeout
	)

	print('✓ Agent initialized')
	print('🔍 Starting agent...\n')

	try:
		result = await agent.run()
		print('\n✅ Agent completed!')
		print(f'\n📊 History length: {len(result.history)}')

		# Check final_result
		final_result = result.final_result()
		print(f'\n🔍 final_result(): {final_result}')

		# Check structured_output
		structured = result.structured_output
		print(f'\n🔍 structured_output: {structured}')

		# Check last result
		if result.history:
			last_history = result.history[-1]
			print(f'\n🔍 Last history result: {last_history.result}')
			if last_history.result:
				last_result = last_history.result[-1]
				print(f'  - is_done: {last_result.is_done}')
				print(f'  - success: {last_result.success}')
				print(f'  - extracted_content: {last_result.extracted_content}')

		# Check if the done message is properly captured
		if final_result and 'Browser opened successfully' in final_result:
			print('\n✅ SUCCESS: Done message captured in final_result!')
		else:
			print(f'\n❌ FAIL: Done message not found. Got: {final_result}')

	except Exception as e:
		print(f'\n❌ Error: {e}')
		import traceback
		traceback.print_exc()


if __name__ == '__main__':
	asyncio.run(main())
