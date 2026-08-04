"""
Save any webpage as a PDF using the save_as_pdf action.

The agent can save the current page as a PDF at any point during a task.
Supports custom filenames, paper sizes (Letter, A4, Legal, A3, Tabloid),
landscape orientation, and background printing.

Setup:
1. Get your API key from https://cloud.browser-use.com/new-api-key
2. Set environment variable: export BROWSER_USE_API_KEY="your-key"
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatBrowserUse


async def main():
	agent = Agent(
		task=(
			'Go to https://news.ycombinator.com and save the front page as a PDF named "hackernews". '
			'Then go to https://en.wikipedia.org/wiki/Web_browser and save just that article as a PDF in A4 format.'
		),
		llm=ChatBrowserUse(model='bu-2-0'),
	)

	history = await agent.run()

	# Print paths of any PDF files the agent saved
	print('\nSaved files:')
	for result in history.action_results():
		if result.attachments:
			for path in result.attachments:
				print(f'  {path}')


if __name__ == '__main__':
	asyncio.run(main())
