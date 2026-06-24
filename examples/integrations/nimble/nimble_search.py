"""Use Nimble as an API-backed search engine inside Browser Use.

The built-in `search` action normally navigates the browser to Google/Bing/
DuckDuckGo and scrapes the rendered page. With `engine="nimble"` it calls Nimble's
search API and returns structured results (title, URL, snippet) in one step — no
navigation, no CAPTCHA risk — which is handy for research/extraction tasks.

Setup:
	uv pip install 'browser-use[nimble]'
	export NIMBLE_API_KEY='your-key'    # get a key from Nimble

Run from the repository root:
	uv run python examples/integrations/nimble/nimble_search.py
"""

import asyncio
import os

from browser_use import Agent, ChatBrowserUse

if not os.environ.get('NIMBLE_API_KEY'):
	raise SystemExit('NIMBLE_API_KEY is not set — get a key from Nimble and export it before running.')


async def main():
	# Steer the built-in search action to Nimble's API-backed engine.
	task = (
		"Use the search action with engine='nimble' to find the latest browser-use "
		'release notes, then summarize the top 3 results with their URLs.'
	)
	agent = Agent(task=task, llm=ChatBrowserUse())
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
