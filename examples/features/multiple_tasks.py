import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_google_genai import ChatGoogleGenerativeAI
from playwright.async_api import async_playwright
from pydantic import SecretStr

from browser_use import Agent
from browser_use.browser import BrowserSession

api_key = os.getenv('GOOGLE_API_KEY')

if not api_key:
	raise ValueError('GOOGLE_API_KEY is not set')

llm = ChatGoogleGenerativeAI(model='gemini-2.0-flash', api_key=SecretStr(api_key))


async def main():
	async with async_playwright() as p:
		browser = await p.chromium.launch(
			headless=False,
		)

		context = await browser.new_context(
			viewport={'width': 1502, 'height': 853},
			ignore_https_errors=True,
		)

		agent = Agent(
			browser_session=BrowserSession(
				browser_context=context,
			),
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
			await context.close()
			await browser.close()


if __name__ == '__main__':
	asyncio.run(main())
