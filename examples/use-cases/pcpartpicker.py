import asyncio

from browser_use import Agent, Browser, ChatBrowserUse, Tools


async def main():
	browser = Browser(cdp_url='http://localhost:9222')

	llm = ChatBrowserUse()

	tools = Tools()

	task = """
    Design me a mid-range water-cooled ITX computer
    Keep the total budget under $2000

    Go to https://pcpartpicker.com/
    Make sure the build is complete and has no incompatibilities.
    Provide the full list of parts with prices and a link to the completed build.
    """

	agent = Agent(
		task=task,
		browser=browser,
		tools=tools,
		llm=llm,
	)

	history = await agent.run(max_steps=100000)
	return history


if __name__ == '__main__':
	history = asyncio.run(main())
	final_result = history.final_result()
	print(final_result)
