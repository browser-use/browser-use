import asyncio
import os

from langchain_ollama import ChatOllama

from browser_use import Agent
from browser_use.utils import BrowserSessionManager, with_error_handling

@with_error_handling()
async def run_script():
	agent = Agent(
		task=(
			'1. Go to https://www.reddit.com/r/LocalLLaMA'
			"2. Search for 'browser use' in the search bar"
			'3. Click search'
			'4. Call done'
		),
		llm=ChatOllama(
			# model='qwen2.5:32b-instruct-q4_K_M',
			# model='qwen2.5:14b',
			model='qwen2.5:latest',
			num_ctx=128000,
		),
		max_actions_per_step=1,
		tool_call_in_content=False,
	)
	async with BrowserSessionManager.manage_browser_session(agent) as managed_agent:
		await managed_agent.run()

if __name__ == '__main__':
    run_script()
