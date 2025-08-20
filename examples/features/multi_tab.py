"""
Simple try of the agent.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatOpenAI

# video: https://preview.screen.studio/share/clenCmS6
llm = ChatOpenAI(model='gpt-4.1-mini')
agent = Agent(
	task='open 3 tabs with elon musk, sam altman, and steve jobs, then go back to the first and stop',
	llm=llm,
)


async def main():
	await agent.run()


asyncio.run(main())
