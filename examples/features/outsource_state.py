"""
Show how to use custom outputs.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import os
import sys

import anyio

from browser_use.agent.views import AgentState
from browser_use.browser.browser import Browser, BrowserConfig

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import Agent

load_dotenv()


async def main():
	task = 'Go to hackernews show hn and give me the first  5 posts'

	browser = Browser(
		config=BrowserConfig(
			headless=True,
		)
	)

	browser_context = await browser.new_context()

	agent_state = AgentState()

	for i in range(10):
		agent = Agent(
			task=task,
			llm=ChatOpenAI(model='gpt-4o'),
			browser=browser,
			browser_context=browser_context,
			injected_agent_state=agent_state,
			page_extraction_llm=ChatOpenAI(model='gpt-4o-mini'),
		)

		done, valid = await agent.take_step()
		print(f'Step {i}: Done: {done}, Valid: {valid}')

		if done and valid:
			break

		agent_state.history.history = []

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
