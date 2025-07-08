import argparse
import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.controller.service import Controller
from browser_use.llm import ChatAnthropic, ChatOpenAI


def get_llm(provider: str):
	if provider == 'anthropic':
		return ChatAnthropic(model='claude-3-5-sonnet-20240620', temperature=0.0)
	elif provider == 'openai':
		return ChatOpenAI(model='gpt-4.1', temperature=0.0)

	else:
		raise ValueError(f'Unsupported provider: {provider}')


# NOTE: This example is to find your current user agent string to use it in the browser_context
task = 'go to https://whatismyuseragent.com and find the current user agent string '


controller = Controller()


parser = argparse.ArgumentParser()
parser.add_argument('--query', type=str, help='The query to process', default=task)
parser.add_argument(
	'--provider',
	type=str,
	choices=['openai', 'anthropic'],
	default='openai',
	help='The model provider to use (default: openai)',
)

args = parser.parse_args()

llm = get_llm(args.provider)

browser_session = BrowserSession(
	browser_profile=BrowserProfile(
		user_agent='foobarfoo',
		user_data_dir='~/.config/browseruse/profiles/default',
	)
)

agent = Agent(
	task=args.query,
	llm=llm,
	controller=controller,
	browser_session=browser_session,
	use_vision=True,
	max_actions_per_step=1,
)


async def main():
	await agent.run(max_steps=25)

	input('Press Enter to close the browser...')
	await browser_session.close()


asyncio.run(main())
