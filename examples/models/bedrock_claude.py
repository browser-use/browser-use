"""
Automated news analysis and sentiment scoring using Bedrock.

@dev Ensure AWS environment variables are set correctly for Bedrock access.
"""

import os
import sys

from langchain_aws import ChatBedrock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import argparse
import asyncio

from browser_use import Agent
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.controller.service import Controller


def get_llm():
    return ChatBedrock(
        model_id="us.anthropic.claude-3-5-sonnet-20241022-v2:0",
        temperature=0.0,
        max_tokens=None,
    )


# Define the task for the agent
task = (
    "Visit cnn.com, navigate to the 'World News' section, and identify the latest headline. "
    "Open the first article and summarize its content in 3-4 sentences. "
    "Additionally, analyze the sentiment of the article (positive, neutral, or negative) "
    "and provide a confidence score for the sentiment. Present the result in a tabular format."
)

parser = argparse.ArgumentParser()
parser.add_argument('--query', type=str, help='The query for the agent to execute', default=task)
args = parser.parse_args()

llm = get_llm()

browser = Browser(
    config=BrowserConfig(
        # chrome_instance_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    )
)

agent = Agent(
    task=args.query, llm=llm, controller=Controller(), browser=browser, validate_output=True,
)


async def main():
    await agent.run(max_steps=30)
    await browser.close()


asyncio.run(main())
