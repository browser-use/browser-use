"""Use OpenAI browser tools and Bash with a Cloud browser."""

import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit

from openai import AsyncOpenAI
from openai.lib.browser import BROWSER_MEMBERS, AsyncBrowserToolset
from openai.lib.responses_tool_runner import AsyncResponsesToolRunner

from browser_use.integrations.openai import Bash, BrowserUse


async def allow_url(context, url):
	parsed = urlsplit(url)
	return parsed.scheme in {'http', 'https'} and not parsed.username and not parsed.password


async def confirm(context):
	return True


async def main():
	model = os.environ['OPENAI_MODEL']
	async with AsyncOpenAI(max_retries=5, timeout=180) as client, BrowserUse(use_cloud=True) as driver:
		tools = AsyncBrowserToolset(
			driver,
			members=BROWSER_MEMBERS,
			confirm=confirm,
			url_policy=allow_url,
		)
		runner = AsyncResponsesToolRunner(browser=tools, functions=[Bash(output_dir=Path('outputs'))])
		try:
			response = await runner.run(
				client,
				{
					'model': model,
					'store': False,
					'input': 'Open https://example.com, follow Learn more, and save a source-backed summary in summary.md using Bash.',
					'context_management': [{'type': 'compaction', 'compact_threshold': 60000}],
				},
				max_steps=100,
			)
			print(response.output_text)
		finally:
			runner.close()
			tools.close()


if __name__ == '__main__':
	asyncio.run(main())
