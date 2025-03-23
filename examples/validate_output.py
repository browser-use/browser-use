"""
Demostrate output validator.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from browser_use import ActionResult, Agent, Controller
from browser_use.utils import BrowserSessionManager, with_error_handling

load_dotenv()

controller = Controller()


class DoneResult(BaseModel):
	title: str
	comments: str
	hours_since_start: int


# we overwrite done() in this example to demonstrate the validator
@controller.registry.action('Done with task', param_model=DoneResult)
async def done(params: DoneResult):
	result = ActionResult(is_done=True, extracted_content=params.model_dump_json())
	print(result)
	# NOTE: this is clearly wrong - to demonstrate the validator
	# return result
	return 'blablabla'


async def main():
	task = 'Go to hackernews hn and give me the top 1 post'
	model = ChatOpenAI(model='gpt-4o')
	async with BrowserSessionManager.manage_browser_session(
		Agent(task=task, llm=model, controller=controller, validate_output=True)
	) as managed_agent:
		await managed_agent.run(max_steps=5)

@with_error_handling()
async def run_script():
	await main()

if __name__ == '__main__':
	run_script()
