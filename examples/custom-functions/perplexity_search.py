import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

import logging

from pydantic import BaseModel

from browser_use import ActionResult, Agent, Controller
from browser_use.browser.profile import BrowserProfile
from browser_use.llm import ChatOpenAI

logger = logging.getLogger(__name__)


class Person(BaseModel):
	name: str
	email: str | None = None


class PersonList(BaseModel):
	people: list[Person]


PERPLEXITY_API_KEY = os.getenv('PERPLEXITY_API_KEY')
if not PERPLEXITY_API_KEY:
	raise ValueError('PERPLEXITY_API_KEY is not set')

controller = Controller(exclude_actions=['search_google'], output_model=PersonList)


@controller.registry.action('Search the web for a specific query with perplexity')
async def search_web(query: str):
	import httpx

	url = 'https://api.perplexity.ai/chat/completions'

	payload = {
		'model': 'sonar',
		'messages': [
			{'role': 'system', 'content': 'Be precise and concise.'},
			{'role': 'user', 'content': query},
		],
	}
	headers = {'Authorization': f'Bearer {PERPLEXITY_API_KEY}', 'Content-Type': 'application/json'}

	async with httpx.AsyncClient() as client:
		response = await client.post(url, json=payload, headers=headers)
		response.raise_for_status()
		response_json = response.json()
		content = response_json['choices'][0]['message']['content']
		citations = response_json['citations']
		output = f'{content}\n\nCitations:\n' + '\n'.join(citations)
		logger.info(output)
		return ActionResult(extracted_content=output, include_in_memory=True)


names = [
	'Ruedi Aebersold',
	'Bernd Bodenmiller',
	'Eugene Demler',
]


async def main():
	task = 'use search_web with "find email address of the following ETH professor:" for each of the persons. Finally return the list with name and email if provided '
	task += '\n' + '\n'.join(names)
	model = ChatOpenAI(model='gpt-4.1')
	browser_profile = BrowserProfile()
	agent = Agent(task=task, llm=model, controller=controller, browser_profile=browser_profile)

	history = await agent.run()

	result = history.final_result()
	if result:
		parsed: PersonList = PersonList.model_validate_json(result)

		for person in parsed.people:
			print(f'{person.name} - {person.email}')
	else:
		print('No result')


if __name__ == '__main__':
	asyncio.run(main())
