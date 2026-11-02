"""Run Kimi K3 through Fireworks with a local browser."""

import asyncio
import os

from browser_use import Agent, Browser


async def main():
	api_key = os.getenv('FIREWORKS_API_KEY')
	if not api_key:
		raise ValueError('Set FIREWORKS_API_KEY. Create a key at https://app.fireworks.ai/settings/users/api-keys')
	async with Agent(
		task='Open https://news.ycombinator.com and return the title of the top story.',
		model='fireworks/accounts/fireworks/models/kimi-k3',
		api_key=api_key,
		model_info={
			'api': 'openai-completions',
			'baseUrl': 'https://api.fireworks.ai/inference/v1',
			'vision': True,
		},
		browser=Browser.chromium(),
	) as agent:
		result = await agent.run()
		print(result.final_result())


if __name__ == '__main__':
	asyncio.run(main())
