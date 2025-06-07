import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from stagehand import Stagehand, StagehandConfig

from browser_use.agent.service import Agent


async def main():
	# Configure Stagehand
	# https://pypi.org/project/stagehand-py/
	# https://github.com/browserbase/stagehand-python-examples/blob/main/agent_example.py
	config = StagehandConfig(
		env='BROWSERBASE',
		api_key=os.getenv('BROWSERBASE_API_KEY'),
		project_id=os.getenv('BROWSERBASE_PROJECT_ID'),
		headless=False,
		dom_settle_timeout_ms=3000,
		model_name='gpt-4o',
		self_heal=True,
		wait_for_captcha_solves=True,
		system_prompt='You are a browser automation assistant that helps users navigate websites effectively.',
		model_client_options={'model_api_key': os.getenv('OPENAI_API_KEY')},
		verbose=2,
	)

	# Create a Stagehand client using the configuration object.
	stagehand = Stagehand(
		config=config,
		model_api_key=os.getenv('OPENAI_API_KEY'),
		# server_url=os.getenv('STAGEHAND_SERVER_URL'),
	)

	# Initialize - this creates a new session automatically.
	await stagehand.init()
	print(f'\nCreated new session: {stagehand.session_id}')
	print(f'🌐 View your live browser: https://www.browserbase.com/sessions/{stagehand.session_id}')

	await stagehand.page.goto('https://google.com/')

	await stagehand.page.act('search for openai')

	# Combine with Browser Use
	agent = Agent(task='click the first result', page=stagehand.page)
	await agent.run()

	# go back and forth
	await stagehand.page.act('open the 3 first links on the page in new tabs')

	await Agent(task='click the first result', page=stagehand.page).run()


if __name__ == '__main__':
	asyncio.run(main())
