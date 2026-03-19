"""
To Use It:

Example 1: Using OpenAI (default), with default task: 'go to reddit and search for posts about browser-use'
python command_line.py

Example 2: Using OpenAI with a Custom Query
python command_line.py --query "go to google and search for browser-use"

Example 3: Using Anthropic's Claude Model with a Custom Query
python command_line.py --query "find latest Python tutorials on Medium" --provider anthropic

Example 4: Using DeepSeek
python command_line.py --query "search for AI news" --provider deepseek

Example 5: Using Ollama (local model, no API key needed)
python command_line.py --query "search for AI news" --provider ollama

"""

import argparse
import asyncio
import os
import sys

# Ensure local repository (browser_use) is accessible
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.browser import BrowserSession
from browser_use.tools.service import Tools

SUPPORTED_PROVIDERS = ['openai', 'anthropic', 'deepseek', 'google', 'groq', 'ollama']

# Providers that do not support vision (screenshots in prompts)
NO_VISION_PROVIDERS = {'deepseek', 'groq', 'ollama'}

PROVIDER_ENV_KEYS: dict[str, str] = {
	'openai': 'OPENAI_API_KEY',
	'anthropic': 'ANTHROPIC_API_KEY',
	'deepseek': 'DEEPSEEK_API_KEY',
	'google': 'GOOGLE_API_KEY',
	'groq': 'GROQ_API_KEY',
	'ollama': '',
}


def get_llm(provider: str):
	env_key = PROVIDER_ENV_KEYS.get(provider, '')
	if env_key:
		api_key = os.getenv(env_key)
		if not api_key:
			raise ValueError(f'Error: {env_key} is not set. Please provide a valid API key.')

	if provider == 'openai':
		from browser_use import ChatOpenAI

		return ChatOpenAI(model='gpt-4.1', temperature=0.0)
	elif provider == 'anthropic':
		from browser_use.llm import ChatAnthropic

		return ChatAnthropic(model='claude-sonnet-4-6', temperature=0.0)
	elif provider == 'deepseek':
		from browser_use.llm import ChatDeepSeek

		return ChatDeepSeek(model='deepseek-chat')
	elif provider == 'google':
		from browser_use.llm import ChatGoogle

		return ChatGoogle(model='gemini-3-flash-preview')
	elif provider == 'groq':
		from browser_use.llm import ChatGroq

		return ChatGroq(model='mixtral-8x7b-32768')
	elif provider == 'ollama':
		from browser_use.llm import ChatOllama

		return ChatOllama(model='llama3')
	else:
		raise ValueError(f'Unsupported provider: {provider}')


def parse_arguments():
	"""Parse command-line arguments."""
	parser = argparse.ArgumentParser(description='Automate browser tasks using an LLM agent.')
	parser.add_argument(
		'--query', type=str, help='The query to process', default='go to reddit and search for posts about browser-use'
	)
	parser.add_argument(
		'--provider',
		type=str,
		choices=SUPPORTED_PROVIDERS,
		default='openai',
		help='The model provider to use (default: openai)',
	)
	return parser.parse_args()


def initialize_agent(query: str, provider: str):
	"""Initialize the browser agent with the given query and provider."""
	llm = get_llm(provider)
	tools = Tools()
	browser_session = BrowserSession()
	use_vision = provider not in NO_VISION_PROVIDERS

	return Agent(
		task=query,
		llm=llm,
		tools=tools,
		browser_session=browser_session,
		use_vision=use_vision,
		max_actions_per_step=1,
	), browser_session


async def main():
	"""Main async function to run the agent."""
	args = parse_arguments()
	agent, browser_session = initialize_agent(args.query, args.provider)

	await agent.run(max_steps=25)

	input('Press Enter to close the browser...')
	await browser_session.kill()


if __name__ == '__main__':
	asyncio.run(main())
