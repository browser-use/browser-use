import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatOpenAI

llm = ChatOpenAI(model='gpt-4.1-mini')

# Actions to run BEFORE the main task (without LLM)
initial_actions = [
	{'navigate': {'url': 'https://en.wikipedia.org/wiki/Randomness', 'new_tab': False}},
]

# Actions to run AFTER the task completes successfully (without LLM)
final_actions = [
	{'go_to_url': {'url': 'about:blank'}},  # Navigate to blank page after completion
]

agent = Agent(
	task='What theories are displayed on the page? Give me a short summary.',
	initial_actions=initial_actions,
	final_actions=final_actions,
	llm=llm,
)


async def main():
	history = await agent.run(max_steps=10)
	print(f'Task completed: {history.is_done()}')
	print(f'Final result: {history.final_result()}')


if __name__ == '__main__':
	asyncio.run(main())
