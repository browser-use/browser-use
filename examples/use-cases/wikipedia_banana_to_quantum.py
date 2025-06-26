import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import ChatOpenAI

# video https://preview.screen.studio/share/vuq91Ej8
llm = ChatOpenAI(
	model='gpt-4o',
	temperature=0.0,
)
task = 'go to https://en.wikipedia.org/wiki/Banana and click on buttons on the wikipedia page to go as fast as possible from banna to Quantum mechanics'

browser_session = BrowserSession(
	browser_profile=BrowserProfile(
		viewport_expansion=-1,
		highlight_elements=False,
		user_data_dir='~/.config/browseruse/profiles/default',
	),
)
agent = Agent(task=task, llm=llm, browser_session=browser_session, use_vision=False)


async def main():
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
