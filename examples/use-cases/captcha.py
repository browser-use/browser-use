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

# NOTE: captchas are hard. For this example it works. But e.g. for iframes it does not.
# for this example it helps to zoom in.
llm = ChatOpenAI(model='gpt-4o')
agent = Agent(
	task='go to https://captcha.com/demos/features/captcha-demo.aspx and solve the captcha',
	llm=llm,
)


async def main():
	await agent.run()
	input('Press Enter to exit')


asyncio.run(main())
