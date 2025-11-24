import asyncio

from browser_use import Agent, ChatBrowserUse


async def main() -> None:
	agent = Agent(
		task='Please find the latest commit on browser-use/browser-use repo and tell me the commit message. Please summarize what it is about.',
		llm=ChatBrowserUse(),
		demo_mode=True,
	)
	await agent.run(max_steps=5)


if __name__ == '__main__':
	asyncio.run(main())
