"""
Multi-turn example. Run a first task, then `follow_up_task()` reuses the same
session so the agent's context (browser state, message history, compaction)
carries over without re-attaching a browser.

Run:
    python examples/rust/02_follow_up.py
"""

from __future__ import annotations

import asyncio

from browser_use.rust import Agent


async def main() -> None:
	agent = Agent(task='open hackernews and tell me the top story title', show_events=True)
	first = await agent.run(interactive=False)
	print(f'[example] first session_id:    {first.session_id}')
	print(f'[example] first final_summary:\n{first.final_summary}\n')

	# Continue in the SAME session. The Rust agent reuses the open browser tab
	# and the existing message history.
	second = await agent.follow_up_task('now open the comments page for that story')
	print(f'[example] follow-up session_id: {second.session_id}')
	print(f'[example] follow-up summary:\n{second.final_summary}')


if __name__ == '__main__':
	asyncio.run(main())
