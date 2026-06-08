"""
The simplest possible example for the new Rust-backed Agent.

One line to run:
    uv run python examples/rust/01_simple_task.py
"""

import asyncio

from browser_use.rust import Agent


async def main() -> None:
	result = await Agent(task='go to hackernews and get the last 5 posts', show_events=True).run()
	print(result.final_summary)


if __name__ == '__main__':
	asyncio.run(main())
