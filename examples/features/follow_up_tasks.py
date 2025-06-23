import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, Controller
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import ChatOpenAI

# Initialize the model
llm = ChatOpenAI(
	model='gpt-4o',
	temperature=0.0,
)
# Get your chrome path
browser_session = BrowserSession(
	browser_profile=BrowserProfile(
		executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		keep_alive=True,
		user_data_dir='~/.config/browseruse/profiles/default',
	),
)

controller = Controller()


task = 'Find the founders of browser-use and draft them a short personalized message'

agent = Agent(task=task, llm=llm, controller=controller, browser_session=browser_session)


async def main():
	await agent.run()

	# new_task = input('Type in a new task: ')
	new_task = 'Find an image of the founders'

	agent.add_new_task(new_task)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
