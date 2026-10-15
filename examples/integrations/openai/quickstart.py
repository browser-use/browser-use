"""Read a page through Browser Use actions and the OpenAI tool runner."""

import asyncio
import os
from urllib.parse import urlsplit

from openai import AsyncOpenAI
from openai.lib.browser import AsyncBrowserToolset
from openai.lib.responses_tool_runner import AsyncResponsesToolRunner

from browser_use.integrations.openai import BrowserUse


async def allow_url(context, url):
	parsed = urlsplit(url)
	return parsed.scheme == 'https' and parsed.hostname == 'example.com' and not parsed.username and not parsed.password


async def confirm(context):
	return context['member'] in {'navigate', 'new_tab'}


async def main():
	model = os.environ['OPENAI_MODEL']
	async with AsyncOpenAI(max_retries=0, timeout=60) as client, BrowserUse(use_cloud=True) as driver:
		tools = AsyncBrowserToolset(
			driver,
			members=['new_tab', 'navigate', 'get_page_text'],
			confirm=confirm,
			url_policy=allow_url,
		)
		runner = AsyncResponsesToolRunner(browser=tools)
		try:
			response = await runner.run(
				client,
				{
					'model': model,
					'store': False,
					'input': 'Open https://example.com and read its heading and explanation. Do not follow links.',
				},
				max_steps=6,
			)
			text = await driver.get_page_text({'tab_id': None})
			if 'Example Domain' not in text:
				raise RuntimeError('The browser did not show the expected page.')
			print(response.output_text)
		finally:
			runner.close()
			tools.close()


if __name__ == '__main__':
	asyncio.run(main())
