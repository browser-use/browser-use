"""
Example: Network traffic inspection using the NetworkWatchdog.

Demonstrates how the agent can use check_network_traffic and get_response_body
tools to find hidden API endpoints and extract data directly from XHR/Fetch responses.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatOpenAI

llm = ChatOpenAI(model='gpt-4.1-mini')
agent = Agent(
	task=(
		'Go to https://news.ycombinator.com and use the check_network_traffic tool '
		'to inspect what API calls are being made. Report back the URLs of any XHR/Fetch requests.'
	),
	llm=llm,
)


async def main():
	await agent.run()


asyncio.run(main())
