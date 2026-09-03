"""
Simple parallel multi-agent example.

This launches multiple agents in parallel to work on different tasks simultaneously.
No complex orchestrator - just direct parallel execution.

@file purpose: Demonstrates parallel multi-agent execution using asyncio
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.llm.google import ChatGoogle

# ============================================================================
# 🔧 SIMPLE CONFIGURATION - CHANGE THIS TO YOUR DESIRED TASK
# ============================================================================

MAIN_TASK = 'find age of ronaldo and messi'

# Simple test - let's start with just one person to see what happens
# MAIN_TASK = "find age of elon musk"

# ============================================================================


async def create_subtasks(main_task: str, llm) -> list[str]:
	"""
	Use LLM to break down main task into logical subtasks

	Real examples of how this works:

	Input: "what is the revenue of nvidia, microsoft, tesla"
	Output: [
	    "Find Nvidia's current revenue and financial data",
	    "Find Microsoft's current revenue and financial data",
	    "Find Tesla's current revenue and financial data"
	]

	Input: "what are ages of musk, altman, bezos, gates"
	Output: [
	    "Find Elon Musk's age and birth date",
	    "Find Sam Altman's age and birth date",
	    "Find Jeff Bezos's age and birth date",
	    "Find Bill Gates's age and birth date"
	]

	Input: "what is the population of tokyo, new york, london, paris"
	Output: [
	    "Find Tokyo's current population",
	    "Find New York's current population",
	    "Find London's current population",
	    "Find Paris's current population"
	]

	Input: "name top 10 yc companies by revenue"
	Output: [
	    "Research Y Combinator's top companies by revenue",
	    "Find revenue data for top YC companies",
	    "Compile list of top 10 YC companies by revenue"
	]
	"""

	prompt = f"""
    Break down this main task into individual, separate subtasks where each subtask focuses on ONLY ONE specific person, company, or item:
    
    Main task: {main_task}
    
    RULES:
    - Each subtask must focus on ONLY ONE person/company/item
    - Do NOT combine multiple people/companies/items in one subtask
    - Each subtask should be completely independent
    - If the main task mentions multiple items, create one subtask per item
    
    Return only the subtasks, one per line, without numbering or bullets.
    Each line should focus on exactly ONE person/company/item.
    """

	try:
		# Use the correct method for ChatGoogle
		response = await llm.ainvoke(prompt)

		# Debug: Print the response type and content
		print(f'DEBUG: Response type: {type(response)}')
		print(f'DEBUG: Response content: {response}')

		# Handle different response types - ChatGoogle returns string content
		if hasattr(response, 'content'):
			content = response.content
		elif isinstance(response, str):
			content = response
		elif hasattr(response, 'text'):
			content = response.text
		else:
			# Convert to string if it's some other type
			content = str(response)

		# Split by newlines and clean up
		subtasks = [task.strip() for task in content.strip().split('\n') if task.strip()]

		# Remove any numbering or bullets that the LLM might add
		cleaned_subtasks = []
		for task in subtasks:
			# Remove common prefixes like "1. ", "- ", "* ", etc.
			cleaned = task.lstrip('0123456789.-* ')
			if cleaned:
				cleaned_subtasks.append(cleaned)

		return cleaned_subtasks if cleaned_subtasks else simple_split_task(main_task)
	except Exception as e:
		print(f'Error creating subtasks: {e}')
		# Fallback to simple split
		return simple_split_task(main_task)


def simple_split_task(main_task: str) -> list[str]:
	"""Simple fallback: split task by common separators"""
	task_lower = main_task.lower()

	# Try to split by common separators
	if ' and ' in task_lower:
		parts = main_task.split(' and ')
		return [part.strip() for part in parts if part.strip()]
	elif ', ' in main_task:
		parts = main_task.split(', ')
		return [part.strip() for part in parts if part.strip()]
	elif ',' in main_task:
		parts = main_task.split(',')
		return [part.strip() for part in parts if part.strip()]

	# If no separators found, return the original task
	return [main_task]


async def run_single_agent(task: str, llm, agent_id: int) -> tuple[int, str]:
	"""Run a single agent and return its result"""
	print(f'🚀 Agent {agent_id} starting: {task}')
	print(f'   📝 This agent will focus ONLY on: {task}')
	print(f'   🌐 Creating isolated browser instance for agent {agent_id}')

	try:
		# Create agent with its own browser session (separate browser instance)
		import tempfile

		from browser_use.browser import BrowserSession
		from browser_use.browser.profile import BrowserProfile

		# Create a unique temp directory for this agent's browser data
		temp_dir = tempfile.mkdtemp(prefix=f'browser_agent_{agent_id}_')

		# Create browser profile with custom user data directory and single tab focus
		profile = BrowserProfile()
		profile.user_data_dir = temp_dir
		profile.headless = False  # Set to True if you want headless mode
		profile.keep_alive = False  # Don't keep browser alive after task

		# Add custom args to prevent new tabs and popups
		profile.args = [
			'--disable-popup-blocking',
			'--disable-extensions',
			'--disable-plugins',
			'--disable-images',  # Faster loading
			'--no-first-run',
			'--disable-default-apps',
			'--disable-background-timer-throttling',
			'--disable-backgrounding-occluded-windows',
			'--disable-renderer-backgrounding',
		]

		# Create a new browser session for each agent with the custom profile
		browser_session = BrowserSession(browser_profile=profile)

		# Debug: Check initial tab count
		try:
			await browser_session.start()
			initial_tabs = await browser_session._cdp_get_all_pages()
			print(f'   📊 Agent {agent_id} initial tab count: {len(initial_tabs)}')
		except Exception as e:
			print(f'   ⚠️ Could not check initial tabs for agent {agent_id}: {e}')

		# Create agent with the dedicated browser session and disable auto URL detection
		agent = Agent(task=task, llm=llm, browser_session=browser_session, preload=False)

		# Run the agent with timeout to prevent hanging
		try:
			result = await asyncio.wait_for(agent.run(), timeout=300)  # 5 minute timeout
		except TimeoutError:
			print(f'⏰ Agent {agent_id} timed out after 5 minutes')
			result = 'Task timed out'

		# Debug: Check final tab count
		try:
			final_tabs = await browser_session._cdp_get_all_pages()
			print(f'   📊 Agent {agent_id} final tab count: {len(final_tabs)}')
			for i, tab in enumerate(final_tabs):
				print(f'      Tab {i + 1}: {tab.get("url", "unknown")[:50]}...')
		except Exception as e:
			print(f'   ⚠️ Could not check final tabs for agent {agent_id}: {e}')

		# Extract clean result from the agent history
		clean_result = extract_clean_result(result)

		# Close the browser session for this agent
		try:
			await browser_session.kill()
		except Exception as e:
			print(f'⚠️ Warning: Error closing browser for agent {agent_id}: {e}')

		print(f'✅ Agent {agent_id} completed and browser closed: {task}')

		return agent_id, clean_result

	except Exception as e:
		error_msg = f'Agent {agent_id} failed: {str(e)}'
		print(f'❌ {error_msg}')
		return agent_id, error_msg


def extract_clean_result(agent_result) -> str:
	"""Extract clean result from agent history"""
	try:
		# Get the last result from the agent history
		if hasattr(agent_result, 'all_results') and agent_result.all_results:
			last_result = agent_result.all_results[-1]
			if hasattr(last_result, 'extracted_content') and last_result.extracted_content:
				return last_result.extracted_content

		# Fallback to string representation
		return str(agent_result)
	except Exception:
		return 'Result extraction failed'


async def run_parallel_agents():
	"""Run multiple agents in parallel on different tasks"""

	# Use Gemini 1.5 Flash
	llm = ChatGoogle(model='gemini-1.5-flash')

	# Main task to break down - use the simple configuration
	main_task = MAIN_TASK

	print(f'🎯 Main task: {main_task}')
	print('🧠 Creating subtasks using LLM...')

	# Create subtasks using LLM
	subtasks = await create_subtasks(main_task, llm)

	print(f'📋 Created {len(subtasks)} subtasks:')
	for i, task in enumerate(subtasks, 1):
		print(f'  {i}. {task}')

	print(f'\n🔥 Starting {len(subtasks)} agents in parallel...')
	print('🔍 Each agent will get its own browser instance with exactly ONE tab')
	print(f'📊 Expected: {len(subtasks)} browser instances, {len(subtasks)} tabs total')

	# Create tasks for parallel execution
	agent_tasks = [run_single_agent(task, llm, i + 1) for i, task in enumerate(subtasks)]

	# Run all agents in parallel using asyncio.gather
	results = await asyncio.gather(*agent_tasks)

	# Print results
	print('\n' + '=' * 60)
	print('📊 PARALLEL EXECUTION RESULTS')
	print('=' * 60)

	for agent_id, result in results:
		print(f'\n🤖 Agent {agent_id} result:')
		print(f'Task: {subtasks[agent_id - 1]}')
		print(f'Result: {result}')
		print('-' * 50)

	print(f'\n🎉 All {len(subtasks)} parallel agents completed!')


def main():
	"""Main function to run parallel agents"""
	# Check if Google API key is available
	api_key = os.getenv('GOOGLE_API_KEY')
	if not api_key:
		print('❌ Error: GOOGLE_API_KEY environment variable not set')
		print('Please set your Google API key to use parallel agents')
		print('You can set it with: export GOOGLE_API_KEY="your-key-here"')
		sys.exit(1)

	# Check if API key looks valid (Google API keys are typically 39 characters)
	if len(api_key) < 20:
		print(f'⚠️  Warning: GOOGLE_API_KEY seems too short ({len(api_key)} characters)')
		print('Google API keys are typically 39 characters long')
		print('Continuing anyway, but this might cause authentication issues...')

	print('🚀 Starting parallel multi-agent example...')
	print(f'📝 Task: {MAIN_TASK}')
	print('This will dynamically create agents based on task complexity')
	print('-' * 60)

	asyncio.run(run_parallel_agents())


if __name__ == '__main__':
	main()
