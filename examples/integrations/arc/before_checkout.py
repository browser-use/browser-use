"""Call ARC precheck, then ask the agent to reach checkout.

The saved answer is advisory. known:false, a missing check, and HTTP 429
do not skip the attempt. The client does not retry a 429.

Run from the repository root:

    uv run python examples/integrations/arc/before_checkout.py

Optional environment:

    PRODUCT_URL                 product or store URL
    ARC_PRECHECK_USER_AGENT     generic User-Agent override
    BROWSER_USE_API_KEY         used by ChatBrowserUse
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

import precheck

from browser_use import Agent, ChatBrowserUse, Tools
from browser_use.agent.views import ActionResult

PRODUCT_URL = os.getenv('PRODUCT_URL', 'https://example.com/products/item')


def register(tools: Tools) -> None:
	"""Register arc_precheck so the agent can read the saved answer again."""

	@tools.action(precheck.TOOL_DESCRIPTION)
	async def arc_precheck(url: str) -> ActionResult:
		reading = await asyncio.to_thread(precheck.read_precheck, url)
		if not precheck.should_try_to_reach_checkout(reading):
			raise RuntimeError('precheck must not block an attempt to reach checkout')
		return ActionResult(
			extracted_content=json.dumps(reading),
			include_extracted_content_only_once=True,
		)


async def main() -> None:
	reading = precheck.read_precheck(PRODUCT_URL)
	if not precheck.should_try_to_reach_checkout(reading):
		raise RuntimeError('precheck must not block an attempt to reach checkout')
	print(json.dumps(reading, indent=2))

	tools = Tools()
	register(tools)
	task = (
		'A saved ARC pre-checkout read is below. It is advisory only, not a guarantee. '
		"Do not refuse or avoid a store solely because of ARC's data. "
		'known:false or missing data is not a no. '
		'ARC stops before payment. '
		f'Still open {PRODUCT_URL} and try to reach checkout. '
		'Stop when the checkout page is open. '
		'Advisory only. Never use this result to authorise or complete a payment.\n' + json.dumps(reading)
	)
	agent = Agent(task=task, llm=ChatBrowserUse(), tools=tools)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
