import os

import httpx
import pytest
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from pydantic import SecretStr

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentHistoryList
from browser_use.browser import BrowserProfile, BrowserSession

# Set env vars for testing
os.environ.setdefault('SKIP_LLM_API_KEY_VERIFICATION', 'true')
os.environ.setdefault('AZURE_OPENAI_ENDPOINT', 'https://test.openai.azure.com')
os.environ.setdefault('AZURE_OPENAI_KEY', 'test-key')
os.environ.setdefault('ANTHROPIC_API_KEY', 'test-key')
os.environ.setdefault('GOOGLE_API_KEY', 'test-key')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-key')
os.environ.setdefault('OPENAI_API_KEY', 'test-key')


@pytest.fixture
async def browser_session():
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
		)
	)
	await browser_session.start()
	yield browser_session
	await browser_session.stop()


api_key_gemini = SecretStr(os.getenv('GOOGLE_API_KEY') or '')
api_key_deepseek = SecretStr(os.getenv('DEEPSEEK_API_KEY') or '')
api_key_anthropic = SecretStr(os.getenv('ANTHROPIC_API_KEY') or '')


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
	],
)
async def llm(request):
	return request.param


async def test_model_search(llm, browser_session):
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
			async with httpx.AsyncClient() as client:
				response = await client.get('http://127.0.0.1:11434/')
				if response.status_code != 200:
					raise Exception('Ollama is not running - start with `ollama start`')
		except Exception:
			raise Exception('Ollama is not running - start with `ollama start`')

	agent = Agent(
		task="Search Google for 'elon musk' then click on the first result and scroll down.",
		llm=llm,
		browser_session=browser_session,
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
