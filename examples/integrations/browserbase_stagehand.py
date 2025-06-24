"""
EXPERIMENTAL: Integration example with Stagehand (browserbase)

This example shows how to combine browser-use with Stagehand for advanced browser automation.
Note: This requires the stagehand-py library to be installed separately:
    pip install stagehand-py

The exact API may vary depending on the stagehand-py version.
Please refer to the official Stagehand documentation for the latest usage:
    https://pypi.org/project/stagehand-py/
    https://github.com/browserbase/stagehand-python-examples/
"""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from stagehand import Stagehand, StagehandConfig  # type: ignore

from browser_use.agent.service import Agent


async def main():
	# Configure Stagehand
	# https://pypi.org/project/stagehand-py/
	# https://github.com/browserbase/stagehand-python-examples/blob/main/agent_example.py
	# Note: This example requires the stagehand-py library to be installed
	# pip install stagehand-py

	# Create StagehandConfig with correct parameters
	# The exact parameters depend on the stagehand-py version
	config = StagehandConfig(  # type: ignore
		apiKey=os.getenv('BROWSERBASE_API_KEY'),
		projectId=os.getenv('BROWSERBASE_PROJECT_ID'),
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

	# Check if stagehand has a page attribute
	if hasattr(stagehand, 'page') and stagehand.page:
		await stagehand.page.goto('https://google.com/')
		await stagehand.page.act('search for openai')
	else:
		print('Warning: Stagehand page not available')

	# Combine with Browser Use
	agent = Agent(task='click the first result', page=stagehand.page)  # type: ignore
	await agent.run()

	# go back and forth
	await stagehand.page.act('open the 3 first links on the page in new tabs')  # type: ignore

	await Agent(task='click the first result', page=stagehand.page).run()  # type: ignore


if __name__ == '__main__':
	asyncio.run(main())
