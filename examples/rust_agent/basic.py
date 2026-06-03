"""Run the Rust-backed Browser Use Agent.

Set BROWSER_USE_TERMINAL_BINARY when the terminal binary is not on PATH.
Set BU_CDP_URL or BROWSER_USE_CDP_URL to attach to a remote Browser Use cloud browser.
"""

import asyncio
import os

from browser_use import BrowserSession
from browser_use.rust import Agent


async def main() -> None:
	cdp_url = os.environ.get('BU_CDP_URL') or os.environ.get('BROWSER_USE_CDP_URL')
	browser_session = BrowserSession(cdp_url=cdp_url) if cdp_url else None
	task = os.environ.get('BU_TASK', 'Open https://example.com and report the page title.')
	max_steps = int(os.environ.get('BU_MAX_STEPS', '20'))

	agent = Agent(task=task, browser_session=browser_session)
	history = await agent.run(max_steps=max_steps)
	print(history.final_result() or '(no final result)')


if __name__ == '__main__':
	asyncio.run(main())
