# pyright: reportMissingImports=false
"""
Automated news analysis and sentiment scoring using Bedrock.

Ensure you have browser-use installed with `examples` extra, i.e. `uv install 'browser-use[examples]'`

@dev Ensure AWS environment variables are set correctly for Bedrock access.
"""

import argparse
import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

import boto3  # type: ignore
from botocore.config import Config
from langchain_aws import ChatBedrockConverse  # type: ignore

from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.controller.service import Controller


def get_llm():
	config = Config(retries={'max_attempts': 10, 'mode': 'adaptive'})
	bedrock_client = boto3.client('bedrock-runtime', region_name='us-east-1', config=config)

	return ChatBedrockConverse(
		model_id='us.anthropic.claude-3-5-sonnet-20241022-v2:0',
		temperature=0.0,
		max_tokens=None,
		client=bedrock_client,
	)


# Define the task for the agent
task = (
	"Visit cnn.com, navigate to the 'World News' section, and identify the latest headline. "
	'Open the first article and summarize its content in 3-4 sentences. '
	'Additionally, analyze the sentiment of the article (positive, neutral, or negative) '
	'and provide a confidence score for the sentiment. Present the result in a tabular format.'
)

parser = argparse.ArgumentParser()
parser.add_argument('--query', type=str, help='The query for the agent to execute', default=task)
args = parser.parse_args()

llm = get_llm()

browser_profile = BrowserProfile(
	# executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
)
browser_session = BrowserSession(browser_profile=browser_profile)

agent = Agent(
	task=args.query,
	llm=llm,
	controller=Controller(),
	browser_session=browser_session,
	validate_output=True,
)


async def main():
	await agent.run(max_steps=30)
	await browser_session.close()


asyncio.run(main())
