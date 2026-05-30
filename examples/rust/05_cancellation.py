"""
Cancellation that actually cancels.

asyncio.CancelledError on the task → `Agent.cancel()` →
`browser-use-terminal cancel <session_id>` (graceful) → SIGINT → terminate
→ kill. The browser is closed and the session state is persisted before
exit.

Run:
    python examples/terminal/05_cancellation.py
"""

from __future__ import annotations

import asyncio

from browser_use.rust import Agent


async def main() -> None:
	agent = Agent(task='go to https://news.ycombinator.com and summarise every story on the front page in detail')

	async def stop_after_3s() -> None:
		await asyncio.sleep(3)
		print('[example] requesting cancellation after 3s …')
		await agent.cancel()

	asyncio.create_task(stop_after_3s())

	result = await agent.run(interactive=False)
	print(f'[example] status:        {result.status}')
	print(f'[example] exit_code:     {result.exit_code}')
	print(f'[example] events seen:   {len(result.events)}')
	print(f'[example] tool calls:    {len(result.steps)}')
	print(f'[example] duration:      {result.duration_seconds:.2f}s')


if __name__ == '__main__':
	asyncio.run(main())
