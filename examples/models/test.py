import asyncio
import os
from typing import Union

import lucidicai as lai
from dotenv import load_dotenv
from langchain.chat_models import ChatOpenAI
from langchain.schema.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from lucidicai.client import Client
from lucidicai.errors import LucidicNotInitializedError
from pydantic import SecretStr

import browser_use.agent.prompts as prompt_module
from browser_use import Agent, BrowserConfig
from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContextConfig

load_dotenv()
gemini_api_key = os.getenv('GEMINI_API_KEY')
openai_api_key = os.getenv('OPENAI_API_KEY')
if not gemini_api_key or not openai_api_key:
	raise ValueError('Missing API keys')

# Define model configurations
llm_configs = [
	{'name': 'gemini-2.0-flash', 'provider': 'google', 'api_key': SecretStr(gemini_api_key)},
	{'name': 'gpt-4.1-nano', 'provider': 'openai', 'api_key': openai_api_key},
]

# Define test tasks and prompt labels
tasks_to_test = ['Search Hello world on google']
prompt_labels = ['production', 'development', 'development']

# Shared browser instance
browser = Browser(
	config=BrowserConfig(
		new_context_config=BrowserContextConfig(
			viewport_expansion=0,
			highlight_elements=False,
		)
	)
)


# Main test runner
async def run_with_label(task: str, llm_name: str, provider: str, api_key, prompt_label: str):
	session_name = f'prompt_{prompt_label} | {llm_name} | {task[:30]}...'

	# Reset Lucidic if initialized
	try:
		Client().reset()
	except LucidicNotInitializedError:
		pass

	# Init Lucidic
	lai.init(task=task, session_name=session_name, mass_sim_id='a89c61f9-1a16-4a68-85f3-31cd2eca8abc')

	# Patch SystemPrompt to use dynamic label
	original_system_prompt_class = prompt_module.SystemPrompt
	original_init = original_system_prompt_class.__init__
	original_loader = original_system_prompt_class._load_prompt_template

	def patched_system_prompt_init(self, *args, **kwargs):
		original_init(self, *args, **kwargs)
		try:
			content = lai.Client().get_prompt('System Prompt', label=prompt_label, cache_ttl=0)
			self.system_message = SystemMessage(content=content.format(max_actions=self.max_actions_per_step))
		except Exception:
			pass  # fallback to default

	def patched_loader(self):
		self.prompt_template = '{{max_actions}}'

	original_system_prompt_class.__init__ = patched_system_prompt_init
	original_system_prompt_class._load_prompt_template = patched_loader

	# Patch PlannerPrompt to use dynamic label
	original_planner_prompt_class = prompt_module.PlannerPrompt

	class LabelInjectedPlannerPrompt(original_planner_prompt_class):
		def get_system_message(self, is_planner_reasoning, label=None) -> Union[SystemMessage, HumanMessage]:
			try:
				content = lai.get_prompt('Planner Prompt', label=prompt_label, cache_ttl=0)
				return SystemMessage(content=content)
			except Exception:
				return super().get_system_message(is_planner_reasoning, label=prompt_label)

	prompt_module.PlannerPrompt = LabelInjectedPlannerPrompt

	# Create LLM
	if provider == 'google':
		llm = ChatGoogleGenerativeAI(model=llm_name, api_key=api_key)
	elif provider == 'openai':
		llm = ChatOpenAI(model=llm_name, api_key=api_key)
	else:
		raise ValueError(f'Unsupported provider: {provider}')

	try:
		agent = Agent(
			task=task,
			llm=llm,
			max_actions_per_step=4,
			browser=browser,
		)
		handler = lai.LucidicLangchainHandler()
		handler.attach_to_llms(agent)
		await agent.run(max_steps=25)
	finally:
		# Restore patched classes
		prompt_module.PlannerPrompt = original_planner_prompt_class
		original_system_prompt_class.__init__ = original_init
		original_system_prompt_class._load_prompt_template = original_loader


# Entrypoint
async def main():
	for task in tasks_to_test:
		for llm in llm_configs:
			for label in prompt_labels:
				await run_with_label(
					task=task,
					llm_name=llm['name'],
					provider=llm['provider'],
					api_key=llm['api_key'],
					prompt_label=label,
				)


if __name__ == '__main__':
	asyncio.run(main())
