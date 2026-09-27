"""Run Anthropic's tool runner with Browser Use and Bash."""

import asyncio
import os
from pathlib import Path

from anthropic import AsyncAnthropic

from browser_use.integrations.anthropic import Bash, BrowserUse


async def main() -> None:
	browser = BrowserUse()
	bash = Bash(output_dir=Path('outputs'))

	async with browser:
		async with AsyncAnthropic() as client:
			runner = client.beta.messages.tool_runner(
				model=os.environ['ANTHROPIC_MODEL'],
				max_tokens=32_768,
				max_iterations=1_000,
				tools=[browser, bash],
				system=(
					'Complete the task autonomously. Use Browser Use for browser actions. '
					'Use Bash for local computation and files in outputs/.'
				),
				messages=[
					{
						'role': 'user',
						'content': 'Open example.com and save its page title to title.txt.',
					}
				],
			)
			final = await runner.until_done()
			print('\n'.join(block.text for block in final.content if block.type == 'text'))


if __name__ == '__main__':
	asyncio.run(main())
