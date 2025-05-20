import asyncio
import itertools
import os

import lucidicai as lai
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from browser_use import Agent, BrowserConfig
from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContextConfig

# From Browseruse Starter Code
load_dotenv()
gemini_api_key = os.getenv('GEMINI_API_KEY')
print(gemini_api_key)
openai_api_key = os.getenv('OPENAI_API_KEY')
groq_api_key = os.getenv('GROQ_API_KEY')
if not gemini_api_key or not openai_api_key or not groq_api_key:
	raise ValueError('Missing API keys')

browser = Browser(
	config=BrowserConfig(
		new_context_config=BrowserContextConfig(
			viewport_expansion=0,
			highlight_elements=False,  # We set this to False to help our grouping
		)
	)
)


async def run_with_label(
	task: str, llm_name: str, provider: str, api_key, use_vision: bool, mass_sim_id: str, mass_sim_name: str, temperature: float
):
	# This is how you initialize your LLM via Langchain from the Browseruse Docs
	if provider == 'google':
		llm = ChatGoogleGenerativeAI(model=llm_name, api_key=api_key, temperature=temperature)
	elif provider == 'openai':
		llm = ChatOpenAI(model=llm_name, api_key=api_key, temperature=temperature)
	elif provider == 'groq':
		llm = ChatGroq(model=llm_name, api_key=api_key, temperature=temperature)
	else:
		raise ValueError(f'Unsupported provider: {provider}')

	agent = Agent(
		task=task,
		llm=llm,
		max_actions_per_step=4,
		browser=browser,
		use_vision=use_vision,
	)

	# This is how you attach Lucidic to your agent
	handler = lai.LucidicLangchainHandler()
	handler.attach_to_llms(agent)
	await agent.run(max_steps=25)


# These are just configs for various LLMs, so you can add more if you want
llm_configs = [
	{'name': 'gemini-2.0-flash', 'provider': 'google', 'api_key': SecretStr(gemini_api_key)},
	{'name': 'gpt-4.1-mini', 'provider': 'openai', 'api_key': openai_api_key},
	{'name': 'meta-llama/llama-4-maverick-17b-128e-instruct', 'provider': 'groq', 'api_key': groq_api_key},
]

# These are just configs for various tasks, so you can add more if you want
tasks_to_test = {
	'NY Rent': 'Find the latest 2 bed and 1.5+ bath apartment listing for rent in New York. ( https://www.redfin.com/ )',
	'Miami Job': 'Search for a job in Miami, Florida, in Human Resources on target. ( https://www.target.com/ )',
	'Solar Panel': 'Find the best solar panel installation company in San Francisco. ( https://www.solarreviews.com/ )',
}
vision_params = [True, False]
temperatures = [0]  # Just a list of different temperature values to test
runs_per_config = 3  # Number of runs per mass sim

configs_to_test = [
	tasks_to_test.items(),
	llm_configs,
	vision_params,
	temperatures,
]


async def main():
	# Loops through each value in each config list
	for (task_name, task), llm, use_vision, temperature in itertools.product(*configs_to_test):
		vision_name = 'with vision' if use_vision else 'without vision'
		mass_sim_name = f'{task_name} | {vision_name} | {llm["name"]}'

		# This is how you initialize Lucidic, creating a mass sim for each combination of configs
		mass_sim_id = lai.create_mass_sim(
			mass_sim_name=mass_sim_name, total_num_sessions=runs_per_config, task=task, tags=[llm['name'], vision_name, task_name]
		)

		for _ in range(runs_per_config):
			lai.init(task=task, session_name=mass_sim_name, mass_sim_id=mass_sim_id)
			await run_with_label(
				task=task,
				llm_name=llm['name'],
				provider=llm['provider'],
				api_key=llm['api_key'],
				use_vision=use_vision,
				mass_sim_id=mass_sim_id,
				mass_sim_name=mass_sim_name,
				temperature=temperature,
			)
			lai.reset()


if __name__ == '__main__':
	asyncio.run(main())
