import asyncio
import os
import sys
import traceback
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from langchain_anthropic import ChatAnthropic

from browser_use import Agent

# Print the API key (first few characters) to verify it's loaded
api_key = os.environ.get('ANTHROPIC_API_KEY', '')
if api_key:
	print(f'API key loaded: {api_key[:10]}...')
else:
	print('API key not found!')

# Define sensitive data to be filtered in logs and outputs
sensitive_data = {'username': 'standard_user', 'password': 'secret_sauce'}

# Initialize the Claude model
llm = ChatAnthropic(model='claude-3-opus-20240229', temperature=0.0, max_tokens=4096)

# Test the LLM connection directly
try:
	print('Testing LLM connection...')
	result = llm.invoke('Hello, can you hear me?')
	print('LLM connection successful!')
	print(f'Response: {result.content[:50]}...')
except Exception as e:
	print(f'Error testing LLM connection: {e}')
	sys.exit(1)

task = 'Buy Sauce Labs Bike Light'

# Define initial actions for page navigation
# Note: Only certain actions are supported as initial actions (open_tab, scroll_down, etc.)
initial_actions = [
	# Open the Sauce Demo website
	{'open_tab': {'url': 'https://www.saucedemo.com/'}},
	# Scroll down slightly to view more content
	{'scroll_down': {'amount': 300}},
]

try:
	print('Creating Agent with initial actions...')
	agent = Agent(task=task, llm=llm, sensitive_data=sensitive_data, initial_actions=initial_actions)
	print('Agent created successfully!')
except Exception as e:
	print(f'Error creating Agent: {e}')
	sys.exit(1)


async def main():
	try:
		print('Running agent...')
		# Set a reasonable timeout for the agent run
		try:
			history = await asyncio.wait_for(agent.run(), timeout=300)  # 5 minute timeout
		except TimeoutError:
			print('Agent run timed out after 5 minutes')
			return

		# Extract Playwright actions to JSON
		output_dir = Path('output')
		output_dir.mkdir(exist_ok=True)

		actions_path = output_dir / 'playwright_actions.json'
		print(f'Extracting Playwright actions to: {actions_path}')
		actions = agent.extract_playwright_actions(output_path=actions_path)

		# Print a summary of the extracted actions
		print(f'Extracted {len(actions)} Playwright actions:')

		# Identify and highlight initial actions
		initial_action_count = len(initial_actions) if hasattr(agent, 'initial_actions') else 0
		if initial_action_count > 0:
			print(f'  Initial actions ({initial_action_count}):')
			for i, action in enumerate(actions[:initial_action_count], 1):
				print(f'    {i}. {action["action_name"]} - {action["params"]}')

			print(f'  History actions ({len(actions) - initial_action_count}):')
			for i, action in enumerate(actions[initial_action_count : initial_action_count + 3], 1):
				print(f'    {i}. {action["action_name"]}')
			if len(actions) - initial_action_count > 3:
				print(f'    ... and {len(actions) - initial_action_count - 3} more actions')
		else:
			# Original behavior if no initial actions
			for i, action in enumerate(actions[:5], 1):
				print(f'  {i}. {action["action_name"]}')
			if len(actions) > 5:
				print(f'  ... and {len(actions) - 5} more actions')

		# Generate a Playwright script with a descriptive name
		print('\nGenerating Playwright script...')
		script_name = 'sauce_demo_purchase'
		script = await agent.generate_playwright_script(actions=actions, headless=False, script_name=script_name)

		# The script is saved in the output/playwright_scripts directory
		script_path = output_dir / 'playwright_scripts'
		print(f'Script directory: {script_path}')

		# We already have the script content in the 'script' variable
		# No need for complex log parsing

		# Print a preview of the generated script
		print('\nGenerated Playwright script preview:')
		script_lines = script.split('\n')
		preview_lines = min(10, len(script_lines))
		for i in range(preview_lines):
			print(script_lines[i])
		print('...')

		print(f'\nFull script saved to the directory: {script_path}')
		print(f'\nYou can run the latest script with: python {script_path}/latest_script.py')
		print('Or check the directory for the exact filename with the timestamp')

	except Exception as e:
		print(f'Error running agent: {e}')
		import traceback

		traceback.print_exc()


async def cleanup():
	"""Cleanup function to handle proper shutdown"""
	print('\nCleaning up resources...')
	# Add any cleanup code here (close connections, save state, etc.)


def handle_sigint(signum, frame):
	"""Handle Ctrl+C gracefully"""
	print('\nReceived interrupt signal. Shutting down...')
	sys.exit(0)


if __name__ == '__main__':
	# Register signal handler for graceful shutdown
	import signal

	signal.signal(signal.SIGINT, handle_sigint)

	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		print('\nScript interrupted by user')
	except Exception as e:
		print(f'\nUnexpected error: {e}')
		traceback.print_exc()
	finally:
		# Run cleanup in a new event loop
		asyncio.run(cleanup())
