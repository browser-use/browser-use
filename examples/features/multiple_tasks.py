import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()


from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.profile import ViewportSize
from browser_use.llm import ChatGoogle

api_key = os.getenv('GOOGLE_API_KEY')

if not api_key:
	raise ValueError('GOOGLE_API_KEY is not set')

llm = ChatGoogle(model='gemini-2.0-flash', api_key=api_key)


async def main():
	# Create browser profile with settings
	browser_profile = BrowserProfile(
		headless=False,
		viewport=ViewportSize(width=1502, height=853),
		ignore_https_errors=True,
	)

	# Create browser session
	browser_session = BrowserSession(
		browser_profile=browser_profile,
	)

	# Start the browser
	await browser_session.start()

	agent = Agent(
		browser_session=browser_session,
		task='Go to https://browser-use.com/',
		llm=llm,
	)

	try:
		result = await agent.run()
		print(f'First task was {"successful" if result.is_successful else "not successful"}')

		if not result.is_successful:
			raise RuntimeError('Failed to navigate to the initial page.')

		agent.add_new_task('Navigate to the documentation page')

		result = await agent.run()
		print(f'Second task was {"successful" if result.is_successful else "not successful"}')

		if not result.is_successful:
			raise RuntimeError('Failed to navigate to the documentation page.')

		while True:
			next_task = input('Write your next task or leave empty to exit\n> ')

			if not next_task.strip():
				print('Exiting...')
				break

			agent.add_new_task(next_task)
			result = await agent.run()

			print(f"Task '{next_task}' was {'successful' if result.is_successful else 'not successful'}")

			if not result.is_successful:
				print('Failed to complete the task. Please try again.')
				continue

	finally:
		# Stop the browser session
		await browser_session.stop()


if __name__ == '__main__':
	asyncio.run(main())
