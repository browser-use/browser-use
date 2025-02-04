import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

from browser_use import LLM, Agent, Browser


async def main():
    browser = Browser()
    async with await browser.new_context() as context:
        llm = LLM(model="openai/gpt-4o")

        # Initialize browser agent
        agent1 = Agent(
            task="Open an online code editor programiz.",
            llm=llm,
            browser_context=context,
        )
        executor = Agent(
            task="Executor. Execute the code written by the coder and suggest some updates if there are errors.",
            llm=llm,
            browser_context=context,
        )

        coder = Agent(
            task="Coder. Your job is to write and complete code. You are an expert coder. Code a simple calculator. Write the code on the coding interface after agent1 has opened the link.",
            llm=llm,
            browser_context=context,
        )
        await agent1.run()
        await executor.run()
        await coder.run()


asyncio.run(main())
