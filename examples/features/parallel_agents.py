import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio

from browser_use import (
    LLM,
    Agent,
    Browser,
    BrowserConfig,
    BrowserContextConfig,
)

browser = Browser(
    config=BrowserConfig(
        disable_security=True,
        headless=False,
        new_context_config=BrowserContextConfig(save_recording_path="./tmp/recordings"),
    )
)
llm = LLM(model="openai/gpt-4o")


async def main():
    agents = [
        Agent(task=task, llm=llm, browser=browser)
        for task in [
            "Search Google for weather in Tokyo",
            "Check Reddit front page title",
            "Look up Bitcoin price on Coinbase",
            "Find NASA image of the day",
            # 'Check top story on CNN',
            # 'Search latest SpaceX launch date',
            # 'Look up population of Paris',
            # 'Find current time in Sydney',
            # 'Check who won last Super Bowl',
            # 'Search trending topics on Twitter',
        ]
    ]

    await asyncio.gather(*[agent.run() for agent in agents])

    # async with await browser.new_context() as context:
    agentX = Agent(
        task="Go to apple.com and return the title of the page",
        llm=llm,
        browser=browser,
        # browser_context=context,
    )
    await agentX.run()

    await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
