"""
Show how to use custom outputs.

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import asyncio
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

import httpx
from pydantic import BaseModel

from browser_use import Agent, ChatOpenAI, Controller
from browser_use.agent.views import ActionResult


class Profile(BaseModel):
	platform: str
	profile_url: str


class Profiles(BaseModel):
	profiles: list[Profile]


controller = Controller(exclude_actions=['search_google'], output_model=Profiles)
BEARER_TOKEN = os.getenv('BEARER_TOKEN')

if not BEARER_TOKEN:
	# use the api key for ask tessa
	# you can also use other apis like exa, xAI, perplexity, etc.
	raise ValueError('BEARER_TOKEN is not set - go to https://www.heytessa.ai/ and create an api key')


@controller.registry.action('Search the web for a specific query')
async def search_web(query: str):
	keys_to_use = ['url', 'title', 'content', 'author', 'score']
	headers = {'Authorization': f'Bearer {BEARER_TOKEN}'}
	async with httpx.AsyncClient() as client:
		response = await client.post(
			'https://asktessa.ai/api/search',
			headers=headers,
			json={'query': query},
		)

	final_results = [
		{key: source[key] for key in keys_to_use if key in source}
		for source in await response.json()['sources']
		if source['score'] >= 0.2
	]
	# print(json.dumps(final_results, indent=4))
	result_text = json.dumps(final_results, indent=4)
	print(result_text)
	return ActionResult(extracted_content=result_text, include_in_memory=True)


async def main():
	task = (
		'Go to this tiktok video url, open it and extract the @username from the resulting url. Then do a websearch for this username to find all his social media profiles. Return me the links to the social media profiles with the platform name.'
		' https://www.tiktokv.com/share/video/7470981717659110678/  '
	)
	model = ChatOpenAI(model='gpt-4.1-mini')
	agent = Agent(task=task, llm=model, controller=controller)

	history = await agent.run()

	result = history.final_result()
	if result:
		parsed: Profiles = Profiles.model_validate_json(result)

		for profile in parsed.profiles:
			print('\n--------------------------------')
			print(f'Platform:         {profile.platform}')
			print(f'Profile URL:      {profile.profile_url}')

	else:
		print('No result')


if __name__ == '__main__':
	asyncio.run(main())
