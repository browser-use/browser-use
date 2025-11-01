"""
Example: Rerunning saved agent history

This example shows how to:
1. Run an agent and save its history (including initial URL navigation)
2. Load and rerun the history with a new agent instance

Useful for:
- Debugging agent behavior
- Testing changes with consistent scenarios
- Replaying successful workflows

Note: Initial actions (like opening URLs from tasks) are now automatically
saved to history and will be replayed during rerun, so you don't need to
worry about manually specifying URLs when rerunning.
"""

import asyncio
from pathlib import Path

from browser_use import Agent
from browser_use.llm.openai.chat import ChatOpenAI


async def main():
	# Example task to demonstrate history saving and rerunning
	history_file = Path('agent_history.json')
	task = 'Go to https://browser-use.github.io/stress-tests/challenges/ember-form.html and fill the form with example data.'
	llm = ChatOpenAI(model='gpt-4.1-mini')

	agent = Agent(task=task, llm=llm, max_actions_per_step=1)
	await agent.run(max_steps=5)
	agent.save_history(history_file)

	rerun_agent = Agent(task='', llm=llm)

	await rerun_agent.load_and_rerun(history_file)


if __name__ == '__main__':
	asyncio.run(main())
