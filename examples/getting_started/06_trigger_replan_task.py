"""
Setup:
1. Get your API key from https://cloud.browser-use.com/new-api-key
2. Set environment variable: export BROWSER_USE_API_KEY="your-key"
"""

import asyncio
import os
import sys

# Add the parent directory to the path so we can import browser_use
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatBrowserUse


async def main():
	llm = ChatBrowserUse(model='bu-2-0-mini-preview')
	task2 = """
    Go to https://the-internet.herokuapp.com/dynamic_controls.

    This is a deliberate replan test. Follow the steps literally:

    1. First output an initial plan_update with 6-8 steps.
       The plan must contain ONLY browser actions.
       Do NOT include "output the plan", "replan", or "report" as plan steps.
    2. Click the "Remove" button.
    3. Wait for the checkbox to disappear.
    4. As the deliberate failure, call find_elements with selector "div[[" exactly once.
       It is an invalid CSS selector and MUST return an error. Do not correct it before the call.
    5. When it fails, do NOT retry the same selector and do NOT give up.
       Output a revised plan_update instead. The revised plan should also contain only browser actions.
    6. Recover by clicking "Add" to restore the checkbox, then select the checkbox.
    7. Enable the input field, type "replanned", and verify the final page state.
    8. Report:
       - the initial plan
       - which step failed
       - the revised plan
       - the final checkbox and input state
    """
	agent = Agent(
		task=task2,
		llm=llm,
		auto_recovery=False,
		enable_planning=True,
		planning_replan_on_stall=1,
		max_actions_per_step=1,
		use_judge=False,
	)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
