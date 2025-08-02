"""
Show how to use custom outputs.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

import anyio

from browser_use import Agent
from browser_use.agent.views import AgentState
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import ChatOpenAI


async def main():
	task = 'Go to hackernews show hn and give me the first  5 posts'

	browser_profile = BrowserProfile(
		headless=True,
	)
	browser_session = BrowserSession(browser_profile=browser_profile)

	agent_state = AgentState()

	for i in range(10):
		agent = Agent(
			task=task,
			llm=ChatOpenAI(model='gpt-4.1'),
			browser_session=browser_session,
			injected_agent_state=agent_state,
			page_extraction_llm=ChatOpenAI(model='gpt-4.1-mini'),
		)

		done, valid = await agent.take_step()
		print(f'Step {i}: Done: {done}, Valid: {valid}')

		if done and valid:
			break

		# Save state to file
		async with await anyio.open_file('agent_state.json', 'w') as f:
			serialized = agent_state.model_dump_json(exclude={'history'})
			await f.write(serialized)

		# Load state back from file
		async with await anyio.open_file('agent_state.json', 'r') as f:
			loaded_json = await f.read()
			agent_state = AgentState.model_validate_json(loaded_json)

		break


if __name__ == '__main__':
	asyncio.run(main())
