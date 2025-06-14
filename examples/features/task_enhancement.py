"""
Task Enhancement Example

This example demonstrates how the browser-use agent automatically enhances task descriptions
to make them more specific, actionable, and clear for browser automation.

The task enhancement feature:
1. Analyzes your original task description during agent.run()
2. Uses an LLM to make it more specific and actionable
3. Adds context, constraints, and clear steps
4. Provides better guidance for the automation agent

Key features demonstrated:
- Automatic task enhancement during agent execution
- Comparing original vs enhanced tasks
- Enabling/disabling task enhancement
- Different types of tasks and their enhancements
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI

from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession

llm = ChatOpenAI(model='gpt-4o')


async def demonstrate_task_enhancement_during_execution():
	"""Demo showing task enhancement during agent execution."""

	print('🧠 Task Enhancement During Execution Demo')
	print('=' * 50)

	# Test cases that show clear enhancement benefits
	test_tasks = ['Find iPhone prices', 'Book flight to Paris', 'Search for laptop deals under $1000']

	print('📝 Original Tasks to be Enhanced:')
	print('-' * 30)

	for i, task in enumerate(test_tasks, 1):
		print(f"{i}. '{task}'")

	print('\n🚀 Executing Enhanced Tasks')
	print('-' * 30)

	async with BrowserSession(
		browser_profile=BrowserProfile(
			headless=False,  # Show browser for demonstration
			window_size={'width': 1280, 'height': 1000},
		)
	) as browser_session:
		# Demonstrate with the first task
		original_task = test_tasks[0]
		print(f"\n📍 Original Task: '{original_task}'")

		# Create agent with enhancement enabled
		agent = Agent(
			task=original_task,
			llm=llm,
			browser_session=browser_session,
			enhance_task=True,  # Enhancement will happen during run()
			enable_memory=False,  # Disable memory to avoid database conflicts in demo
		)

		print(f"🔄 Task before run(): '{agent.task}'")
		print('⚡ Starting agent.run() - task enhancement will happen now...')

		try:
			# Task enhancement happens automatically at start of run()
			history = await agent.run(max_steps=3)

			print(f"✨ Task after enhancement: '{agent.task}'")

			# Show the difference
			if agent.task != original_task:
				print('\n📊 Enhancement Analysis:')
				print(f'   Original length: {len(original_task)} characters')
				print(f'   Enhanced length: {len(agent.task)} characters')
				print(f'   Added detail: {len(agent.task) - len(original_task)} characters')
				print(f'   Enhancement factor: {len(agent.task) / len(original_task):.2f}x')
			else:
				print('   No enhancement was applied (task was already clear)')

			if history.is_successful():
				print('✅ Task completed successfully!')
				print(f'📋 Final result: {history.final_result()}')
			else:
				print('⏸️ Task demonstration completed')

		except Exception as e:
			print(f'⚠️ Demo stopped: {e}')


async def main():
	"""Main function to run all demonstrations."""

	print('🌟 Browser-Use Task Enhancement Feature Demo')
	print('=' * 55)
	print('This demo shows how the browser-use agent automatically enhances')
	print('task descriptions during execution to make them more actionable.\n')

	try:
		# Run the execution demonstration
		await demonstrate_task_enhancement_during_execution()

		print('\n🎉 Demo completed successfully!')

	except Exception as e:
		print(f'\n❌ Demo failed: {e}')


if __name__ == '__main__':
	asyncio.run(main())
