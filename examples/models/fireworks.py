"""
Run the agent on a Fireworks-served model.

@dev You need to add FIREWORKS_API_KEY to your environment variables.
"""

import asyncio
import os

from dotenv import load_dotenv

from browser_use import Agent, ChatOpenAI

load_dotenv()

api_key = os.getenv('FIREWORKS_API_KEY')
if not api_key:
	raise ValueError('FIREWORKS_API_KEY is not set. Get one at https://app.fireworks.ai/settings/users/api-keys')

# Any Fireworks model id works, e.g. accounts/fireworks/models/glm-5p3-flash
llm = ChatOpenAI(
	model='accounts/fireworks/models/kimi-k3',
	base_url='https://api.fireworks.ai/inference/v1',
	api_key=api_key,
)


async def main():
	agent = Agent(
		task='Open https://news.ycombinator.com and return the title of the top story.',
		llm=llm,
	)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
