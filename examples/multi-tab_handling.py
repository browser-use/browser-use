"""
Simple try of the agent.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

from langchain_openai import ChatOpenAI

from browser_use import Agent
from browser_use.utils import BrowserSessionManager, with_error_handling

# video: https://preview.screen.studio/share/clenCmS6
llm = ChatOpenAI(model='gpt-4o')
agent = Agent(
	task='open 3 tabs with elon musk, trump, and steve jobs, then go back to the first and stop',
	llm=llm,
)


@with_error_handling()
async def run_script():
    async with BrowserSessionManager.manage_browser_session(agent) as managed_agent:
        await managed_agent.run()

if __name__ == '__main__':
    run_script()
