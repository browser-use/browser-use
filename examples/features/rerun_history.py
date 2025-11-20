"""
Example: Rerunning saved agent history with variable detection

This example shows how to:
1. Run an agent and save its history (including initial URL navigation)
2. Detect variables in the saved history (emails, names, dates, etc.)
3. Load and rerun the history with a new agent instance

Useful for:
- Debugging agent behavior
- Testing changes with consistent scenarios
- Replaying successful workflows
- Understanding what values can be substituted in reruns

Note: Initial actions (like opening URLs from tasks) are now automatically
saved to history and will be replayed during rerun, so you don't need to
worry about manually specifying URLs when rerunning.
"""

import asyncio
from pathlib import Path

from browser_use import Agent
from browser_use.llm import ChatBrowserUse


async def main():
	# Example task to demonstrate history saving and rerunning
	history_file = Path('agent_history.json')
	task = 'Go to https://browser-use.github.io/stress-tests/challenges/ember-form.html and fill the form with example data.'
	llm = ChatBrowserUse()

	# Step 1: Run the agent and save history
	print('=== Running Agent ===')
	agent = Agent(task=task, llm=llm, max_actions_per_step=1)
	await agent.run(max_steps=5)
	agent.save_history(history_file)
	print(f'✓ History saved to {history_file}')

	# Step 2: Detect variables in the saved history
	print('\n=== Detecting Variables ===')
	variables = agent.detect_variables()
	if variables:
		print(f'Found {len(variables)} variable(s):')
		for var_name, var_info in variables.items():
			format_info = f' (format: {var_info.format})' if var_info.format else ''
			print(f'  • {var_name}: "{var_info.original_value}"{format_info}')
	else:
		print('No variables detected in history')

	# Step 3: Rerun the history with a new agent
	print('\n=== Rerunning History ===')
	rerun_agent = Agent(task='', llm=llm)
	await rerun_agent.load_and_rerun(history_file)
	print('✓ History rerun complete')


if __name__ == '__main__':
	asyncio.run(main())
