import asyncio
import os

import pytest
import requests
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from pydantic import SecretStr

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentHistoryList
from browser_use.browser.browser import Browser, BrowserConfig


@pytest.fixture(scope='function')
def event_loop():
	"""Create an instance of the default event loop for each test case."""
	loop = asyncio.get_event_loop_policy().new_event_loop()
	yield loop
	loop.close()


@pytest.fixture(scope='function')
async def browser(event_loop):
	browser_instance = Browser(
		config=BrowserConfig(
			headless=True,
		)
	)
	yield browser_instance
	await browser_instance.close()


@pytest.fixture
async def context(browser):
	async with await browser.new_context() as context:
		yield context


api_key_gemini = SecretStr(os.getenv('GEMINI_API_KEY') or '')
api_key_deepseek = SecretStr(os.getenv('DEEPSEEK_API_KEY') or '')
api_key_anthropic = SecretStr(os.getenv('ANTHROPIC_API_KEY') or '')
api_key_novita = SecretStr(os.getenv('NOVITA_API_KEY') or '')


# pytest -s -v tests/test_models.py
@pytest.fixture(
	params=[
		ChatOpenAI(model='gpt-4o'),
		ChatOpenAI(model='gpt-4o-mini'),
		AzureChatOpenAI(
			model='gpt-4o',
			api_version='2024-10-21',
			azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT', ''),
			api_key=SecretStr(os.getenv('AZURE_OPENAI_KEY', '')),
		),
		# ChatOpenAI(
		# base_url='https://api.deepseek.com/v1',
		# model='deepseek-reasoner',
		# api_key=api_key_deepseek,
		# ),
		# run: ollama start
		ChatOllama(
			model='qwen2.5:latest',
			num_ctx=128000,
		),
		AzureChatOpenAI(
			model='gpt-4o-mini',
			api_version='2024-10-21',
			azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT', ''),
			api_key=SecretStr(os.getenv('AZURE_OPENAI_KEY', '')),
		),
		ChatAnthropic(
			model_name='claude-3-5-sonnet-20240620',
			timeout=100,
			temperature=0.0,
			stop=None,
			api_key=api_key_anthropic,
		),
		ChatGoogleGenerativeAI(model='gemini-2.0-flash-exp', api_key=api_key_gemini),
		ChatGoogleGenerativeAI(model='gemini-1.5-pro', api_key=api_key_gemini),
		ChatGoogleGenerativeAI(model='gemini-1.5-flash-latest', api_key=api_key_gemini),
		ChatOpenAI(
			base_url='https://api.deepseek.com/v1',
			model='deepseek-chat',
			api_key=api_key_deepseek,
		),
		ChatOpenAI(
			base_url='https://api.novita.ai/v3/openai',
			model='qwen/qwq-32b',
			api_key=api_key_novita,
		),
	],
	ids=[
		'gpt-4o',
		'gpt-4o-mini',
		'azure-gpt-4o',
		#'deepseek-reasoner',
		'qwen2.5:latest',
		'azure-gpt-4o-mini',
		'claude-3-5-sonnet',
		'gemini-2.0-flash-exp',
		'gemini-1.5-pro',
		'gemini-1.5-flash-latest',
		'deepseek-chat',
    'qwen/qwq-32b',
	],
)
async def llm(request):
	return request.param


@pytest.mark.asyncio
async def test_model_search(llm, context):
	"""Test 'Search Google' action"""
	model_name = llm.model if hasattr(llm, 'model') else llm.model_name
	print(f'\nTesting model: {model_name}')

	use_vision = True
	models_without_vision = ['deepseek-chat', 'deepseek-reasoner']
	if hasattr(llm, 'model') and llm.model in models_without_vision:
		use_vision = False
	elif hasattr(llm, 'model_name') and llm.model_name in models_without_vision:
		use_vision = False

	# require ollama run
	local_models = ['qwen2.5:latest']
	if model_name in local_models:
		# check if ollama is running
		# ping ollama http://127.0.0.1
		try:
			response = requests.get('http://127.0.0.1:11434/')
			if response.status_code != 200:
				raise Exception('Ollama is not running - start with `ollama start`')
		except Exception:
			raise Exception('Ollama is not running - start with `ollama start`')

	agent = Agent(
		task="Search Google for 'elon musk' then click on the first result and scroll down.",
		llm=llm,
		browser_context=context,
		max_failures=2,
		use_vision=use_vision,
	)
	history: AgentHistoryList = await agent.run(max_steps=2)
	done = history.is_done()
	successful = history.is_successful()
	action_names = history.action_names()
	print(f'Actions performed: {action_names}')
	errors = [e for e in history.errors() if e is not None]
	errors = '\n'.join(errors)
	passed = False
	if 'search_google' in action_names:
		passed = True
	elif 'go_to_url' in action_names:
		passed = True
	elif 'open_tab' in action_names:
		passed = True

	else:
		passed = False
	print(f'Model {model_name}: {"✅ PASSED - " if passed else "❌ FAILED - "} Done: {done} Successful: {successful}')

	assert passed, f'Model {model_name} not working\nActions performed: {action_names}\nErrors: {errors}'
