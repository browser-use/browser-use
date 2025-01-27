import os
import sys

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from browser_use.browser.context import BrowserContext, BrowserContextConfig

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import argparse
import asyncio

from browser_use import Agent
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.controller.service import Controller


def get_llm(provider: str):
	if provider == 'anthropic':
		return ChatAnthropic(model_name='claude-3-5-sonnet-20240620', timeout=25, stop=None, temperature=0.0)
	elif provider == 'openai':
		return ChatOpenAI(model='gpt-4o', temperature=0.0)

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


browser = Browser(
	config=BrowserConfig(
		# chrome_instance_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
	)
)

browser_context = BrowserContext(config=BrowserContextConfig(user_agent='foobarfoo'), browser=browser)

agent = Agent(
	task=args.query,
	llm=llm,
	controller=controller,
	# browser=browser,
	browser_context=browser_context,
	use_vision=True,
	max_actions_per_step=1,
)


async def main():
	await agent.run(max_steps=25)

	input('Press Enter to close the browser...')
	await browser_context.close()


asyncio.run(main())
