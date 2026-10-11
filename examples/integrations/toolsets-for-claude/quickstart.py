"""Build a Hacker News reading list with Browser Use and Claude.

Requires Linux/macOS with /bin/bash, or WSL on Windows.
"""

import asyncio
from pathlib import Path

from anthropic import AsyncAnthropic
from anthropic.tools.browser import LocalFilePolicy  # pyright: ignore[reportMissingImports]

from browser_use.integrations.toolsets_for_claude import Bash, BrowserUse

TASK = 'Read the first three Hacker News posts and save their titles and URLs to hacker-news.md and hacker-news.json.'

SYSTEM_PROMPT = 'Complete the task with the browser tools and Bash.'


async def main() -> None:
	driver = BrowserUse(
		# use_cloud=True,  # Uncomment and set BROWSER_USE_API_KEY to use Cloud.
		# These tools are disabled by default.
		configs={
			'javascript_exec': {'enabled': True},
			'file_upload': {'enabled': True},
			'read_console': {'enabled': True},
			'read_network': {'enabled': True},
		},
		confirm=lambda _: True,  # Run without approval prompts.
		file_policy=LocalFilePolicy(upload_roots=[Path('uploads'), Path('outputs')]),
	)
	bash = Bash(output_dir=Path('outputs'))

	async with driver, AsyncAnthropic() as client:
		runner = client.beta.messages.tool_runner(
			model='claude-opus-5-5',
			max_tokens=32_768,
			max_iterations=100,
			tools=[driver, bash],
			system=SYSTEM_PROMPT,
			messages=[{'role': 'user', 'content': TASK}],
		)
		final = await runner.until_done()
		print('\n'.join(block.text for block in final.content if block.type == 'text'))


if __name__ == '__main__':
	asyncio.run(main())
