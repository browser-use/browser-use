import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatOpenAI

# This uses a bigger model for the planning
# And a smaller model for the page content extraction
# THink of it like a subagent which only task is to extract content from the current page
llm = ChatOpenAI(model='gpt-4.1')
small_llm = ChatOpenAI(model='gpt-4.1-mini')
task = 'Find the founders of browser-use in ycombinator, extract all links and open the links one by one'
agent = Agent(task=task, llm=llm, page_extraction_llm=small_llm)


async def main():
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
