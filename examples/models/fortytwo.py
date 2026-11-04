"""Run with `uv run examples/models/fortytwo.py` and FORTYTWO_API_KEY set.

Cost totals may omit unpriced calls. A displayed zero does not mean free.
"""

import asyncio

from dotenv import load_dotenv

from browser_use import Agent, ChatFortytwo

load_dotenv()


async def main():
	llm = ChatFortytwo()
	agent = Agent(task='Find the latest Browser Use release on GitHub and return its version.', llm=llm)
	await agent.run(max_steps=10)


if __name__ == '__main__':
	asyncio.run(main())
