"""
To use it, you'll need to install streamlit, and run with:

python -m streamlit run streamlit_demo.py

"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

import streamlit as st  # type: ignore

from browser_use import Agent
from browser_use.browser import BrowserSession
from browser_use.tools.service import Tools

if os.name == 'nt':
	asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


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


# Function to get the LLM based on provider
def get_llm(provider: str):
	env_key = PROVIDER_ENV_KEYS.get(provider, '')
	if env_key:
		api_key = os.getenv(env_key)
		if not api_key:
			st.error(f'Error: {env_key} is not set. Please provide a valid API key.')
			st.stop()

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
		st.error(f'Unsupported provider: {provider}')
		st.stop()
		return None  # Never reached, but helps with type checking


# Function to initialize the agent
def initialize_agent(query: str, provider: str):
	llm = get_llm(provider)
	tools = Tools()
	browser_session = BrowserSession()
	use_vision = provider not in NO_VISION_PROVIDERS

	return Agent(
		task=query,
		llm=llm,  # type: ignore
		tools=tools,
		browser_session=browser_session,
		use_vision=use_vision,
		max_actions_per_step=1,
	), browser_session


# Streamlit UI
st.title('Automated Browser Agent with LLMs 🤖')

query = st.text_input('Enter your query:', 'go to reddit and search for posts about browser-use')
provider = st.radio('Select LLM Provider:', list(PROVIDER_ENV_KEYS.keys()), index=0)

if st.button('Run Agent'):
	st.write('Initializing agent...')
	agent, browser_session = initialize_agent(query, provider)

	async def run_agent():
		with st.spinner('Running automation...'):
			await agent.run(max_steps=25)
		st.success('Task completed! 🎉')

	asyncio.run(run_agent())

	st.button('Close Browser', on_click=lambda: asyncio.run(browser_session.kill()))
