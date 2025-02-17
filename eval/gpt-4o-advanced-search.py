import json
import os
import sys

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import ActionResult, Agent, Controller

load_dotenv()


async def run_agent(task: str, max_steps: int = 38):
	controller = Controller(exclude_actions=['search_google'])
	BEARER_TOKEN = os.getenv('BEARER_TOKEN')

	if not BEARER_TOKEN:
		# use the api key for ask tessa
		# you can also use other apis like exa, xAI, perplexity, etc.
		raise ValueError('BEARER_TOKEN is not set - go to https://www.heytessa.ai/ and create an api key')

	@controller.registry.action('Search the web for a specific query')
	async def search_web(query: str):
		keys_to_use = ['url', 'title', 'content', 'author', 'score']
		headers = {'Authorization': f'Bearer {BEARER_TOKEN}'}
		response = requests.post('https://asktessa.ai/api/search', headers=headers, json={'query': query})

		final_results = [
			{key: source[key] for key in keys_to_use if key in source}
			for source in response.json()['sources']
			if source['score'] >= 0.2
		]
		# print(json.dumps(final_results, indent=4))
		result_text = json.dumps(final_results, indent=4)
		return ActionResult(extracted_content=result_text, include_in_memory=True)

	llm = ChatOpenAI(
		model='gpt-4o',
		temperature=0.0,
	)
	agent = Agent(
		task=task,
		llm=llm,
		controller=controller,
		include_attributes=[
			'title',
			'type',
			'name',
			'role',
			'tabindex',
			'aria-label',
			'placeholder',
			'value',
			'alt',
			'aria-expanded',
			'href',
		],
	)
	result = await agent.run(max_steps=max_steps)
	return result
