"""
Example: Rerunning saved agent history with variable detection and substitution

This example shows how to:
1. Run an agent and save its history (including initial URL navigation)
2. Detect variables in the saved history (emails, names, dates, etc.)
3. Rerun the history with substituted values (different data)
4. Get AI-generated summary of rerun completion (with screenshot analysis)

Useful for:
- Debugging agent behavior
- Testing changes with consistent scenarios
- Replaying successful workflows with different data
- Understanding what values can be substituted in reruns
- Getting automated verification of rerun success

Note: Initial actions (like opening URLs from tasks) are now automatically
saved to history and will be replayed during rerun, so you don't need to
worry about manually specifying URLs when rerunning.

AI Features During Rerun:

1. AI Step for Extract Actions:
   When an 'extract' action is replayed, the rerun automatically uses AI to
   re-analyze the current page content (since it may have changed with new data).
   This ensures the extracted content reflects the current state, not cached results.

2. AI Summary:
   At the end of the rerun, an AI summary analyzes the final screenshot and
   execution statistics to determine success/failure.

Custom LLM Usage:
	# Option 1: Use agent's LLM (default)
	results = await agent.load_and_rerun(history_file)

	# Option 2: Use custom LLMs for AI steps and summary
	from browser_use.llm import ChatOpenAI
	custom_llm = ChatOpenAI(model='gpt-4.1-mini')
	results = await agent.load_and_rerun(
		history_file,
		ai_step_llm=custom_llm,    # For extract action re-evaluation
		summary_llm=custom_llm,     # For final summary
	)

The AI summary will be the last item in results and will have:
	- extracted_content: The summary text
	- success: Whether rerun was successful
	- is_done: Always True for summary
"""

import asyncio
from pathlib import Path

from browser_use import Agent
from browser_use.llm import ChatBrowserUse


async def main():
	# Example task to demonstrate history saving and rerunning
	history_file = Path('agent_history.json')
	task = 'Go to https://browser-use.github.io/stress-tests/challenges/reference-number-form.html and fill the form with example data and submit and extract the refernence number.'
	llm = ChatBrowserUse()

	# Optional: Use custom LLMs for AI features during rerun
	# Uncomment to use a custom LLM:
	# from browser_use.llm import ChatOpenAI
	# custom_llm = ChatOpenAI(model='gpt-4.1-mini')
	# ai_step_llm = custom_llm   # For re-evaluating extract actions
	# summary_llm = custom_llm   # For final summary
	ai_step_llm = None  # Set to None to use agent's LLM (default)
	summary_llm = None  # Set to None to use agent's LLM (default)

	# Step 1: Run the agent and save history
	print('=== Running Agent ===')
	agent = Agent(task=task, llm=llm, max_actions_per_step=1)
	await agent.run(max_steps=10)
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

	# Step 3: Rerun the history with substituted values
	if variables:
		print('\n=== Rerunning History (Substituted Values) ===')
		# Create new values for the detected variables
		new_values = {}
		for var_name, var_info in variables.items():
			# Map detected variables to new values
			if var_name == 'email':
				new_values[var_name] = 'jane.smith@example.com'
			elif var_name == 'full_name':
				new_values[var_name] = 'Jane Smith'
			elif var_name.startswith('full_name_'):
				new_values[var_name] = 'General Information'
			elif var_name == 'first_name':
				new_values[var_name] = 'Jane'
			elif var_name == 'date':
				new_values[var_name] = '1995-05-15'
			elif var_name == 'country':
				new_values[var_name] = 'Canada'
			# You can add more variable substitutions as needed

		if new_values:
			print(f'Substituting {len(new_values)} variable(s):')
			for var_name, new_value in new_values.items():
				old_value = variables[var_name].original_value
				print(f'  • {var_name}: "{old_value}" → "{new_value}"')

		# Rerun with substituted values and optional custom LLMs
		substitute_agent = Agent(task='', llm=llm)
		results = await substitute_agent.load_and_rerun(
			history_file,
			variables=new_values,
			ai_step_llm=ai_step_llm,  # For extract action re-evaluation
			summary_llm=summary_llm,  # For final summary
		)

		# Display AI-generated summary (last result)
		if results and results[-1].is_done:
			summary = results[-1]
			print('\n📊 AI Summary:')
			print(f'  Summary: {summary.extracted_content}')
			print(f'  Success: {summary.success}')
		print('✓ History rerun with substituted values complete')
	else:
		print('\n⚠️  No variables detected, skipping substitution rerun')


if __name__ == '__main__':
	asyncio.run(main())
