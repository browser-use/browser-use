import asyncio
import os

from browser_use import Agent
from browser_use.llm import ChatVolcengine

# Volcengine Ark serves ByteDance's Doubao models over an OpenAI-compatible API.
# Model IDs must carry the full version suffix — the console's short names
# (e.g. 'doubao-seed-2-1-pro') return 404.
api_key = os.getenv('ARK_API_KEY')
if api_key is None:
	print('Make sure you have ARK_API_KEY:')
	print('export ARK_API_KEY=your_key')
	exit(0)


async def main():
	llm = ChatVolcengine(
		model='doubao-seed-2-1-pro-260628',
		api_key=api_key,
	)

	agent = Agent(
		task='Find the current top story on Hacker News and summarize it in one sentence.',
		llm=llm,
	)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
