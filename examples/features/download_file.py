import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()


from browser_use import Agent, Browser, ChatGoogle

api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
	raise ValueError('GOOGLE_API_KEY is not set')

llm = ChatGoogle(model='gemini-2.5-flash', api_key=api_key)


browser = Browser(downloads_path='~/Downloads/tmp')


async def run_download():
	agent = Agent(
		task='Go to "https://file-examples.com/" and download the smallest doc file. then go back and get the next file.',
		llm=llm,
		browser=browser,
	)
	await agent.run(max_steps=25)


if __name__ == '__main__':
	asyncio.run(run_download())
