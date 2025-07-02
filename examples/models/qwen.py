import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_ollama import ChatOllama

from browser_use import Agent

import lucidicai as lai

lai.init("Reddit Search")


async def run_search():
	agent = Agent(
		task=(
			"1. Go to https://www.reddit.com/r/LocalLLaMA2. Search for 'browser use' in the search bar3. Click search4. Call done"
		),
		llm=ChatOllama(
			# model='qwen2.5:32b-instruct-q4_K_M',
			# model='qwen2.5:14b',
			model='qwen2.5:latest',
			num_ctx=128000,
		),
		max_actions_per_step=1,
	)
	handler = lai.LucidicLangchainHandler()
	handler.attach_to_llms(agent)

	await agent.run()

	lai.end_session()


if __name__ == '__main__':
	asyncio.run(run_search())
