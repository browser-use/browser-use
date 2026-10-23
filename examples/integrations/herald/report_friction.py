"""
Let the agent report where it gets stuck on a website, and start with known problems on that site.

Uses Herald (https://github.com/siddhi-bansal/herald-browser-use), which collects these reports
from agents so the site's owners can fix what broke, and turns repeated problems into tips.

Setup:
1. Get your API key from https://cloud.browser-use.com/new-api-key
2. Set environment variable: export BROWSER_USE_API_KEY="your-key"
3. Optional, for tips: run `uv run --with herald-browser-use python -m herald_browser_use signup you@example.com`,
   then export HERALD_API_KEY="the key it prints"

Run (from the repository root; --with adds herald-browser-use to the environment for this run):
uv run --with herald-browser-use examples/integrations/herald/report_friction.py
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from dotenv import load_dotenv

load_dotenv()

from herald_browser_use import herald_tips, herald_tools, report_failed_run  # type: ignore

from browser_use import Agent, ChatBrowserUse

# A demo store with problems planted on purpose, so the agent has something to report.
SITE = 'herald-demo-store.siddhibansal2604.workers.dev'
TASK = f"""
Go to https://{SITE}, add one Harbor Blue Mug to the cart and go to checkout as a guest.
Stop before entering any payment details. If something on the website gets in your way, call report_friction.
"""


def show(body: dict, error: str | None) -> None:
	print(f'Herald report: {body["what_went_wrong"]} ({error or "sent"})')


async def main():
	# Known problems other agents reported on this site ('' if there are none or no HERALD_API_KEY is set)
	tips = await herald_tips(SITE)

	agent = Agent(
		task=TASK + tips,
		llm=ChatBrowserUse(model='bu-2-0-mini-preview'),
		tools=herald_tools(on_report=show),  # adds the report_friction action
	)
	await agent.run()

	# If the run failed and the agent didn't report why, send one report built from its history.
	await report_failed_run(agent, goal='Add one item to the cart and reach checkout as a guest', on_report=show)


if __name__ == '__main__':
	asyncio.run(main())
