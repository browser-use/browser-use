import asyncio
import os
import random
import sys

from browser_use.llm.google.chat import ChatGoogle

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent

llm = ChatGoogle(model='gemini-flash-latest', temperature=1.0)


def check_is_task_stopped():
	async def _internal_check_is_task_stopped() -> bool:
		if random.random() < 0.1:
			print('[TASK STOPPER] Task is stopped')
			return True
		else:
			print('[TASK STOPPER] Task is not stopped')
			return False

	return _internal_check_is_task_stopped


task = """
Go to https://browser-use.github.io/stress-tests/challenges/wufoo-style-form.html and complete the Wufoo-style form by filling in all required fields and submitting.
"""

agent = Agent(task=task, llm=llm, flash_mode=True, register_should_stop_callback=check_is_task_stopped(), max_actions_per_step=1)


async def main():
	await agent.run(max_steps=30)


if __name__ == '__main__':
	asyncio.run(main())
