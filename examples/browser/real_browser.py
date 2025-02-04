import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio

from browser_use import LLM, Agent, Browser, BrowserConfig

browser = Browser(
    config=BrowserConfig(
        # NOTE: you need to close your chrome browser - so that this can open your browser in debug mode
        chrome_instance_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )
)


async def main():
    agent = Agent(
        task="In docs.google.com write my Papa a quick letter",
        llm=LLM(model="openai/gpt-4o"),
        browser=browser,
    )

    await agent.run()
    await browser.close()

    input("Press Enter to close...")


if __name__ == "__main__":
    asyncio.run(main())
