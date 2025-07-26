import asyncio
import os
import pathlib
import shutil

from dotenv import load_dotenv

from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import ChatOpenAI

load_dotenv()

''
SCRIPT_DIR = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
agent_dir = SCRIPT_DIR / 'alphabet_earnings'
agent_dir.mkdir(exist_ok=True)

try:
	from lmnr import Laminar

	Laminar.initialize(project_api_key=os.getenv('LMNR_PROJECT_API_KEY'))
except Exception as e:
	print(f'Error initializing Laminar: {e}')

llm = ChatOpenAI(
	model='o4-mini',
)

browser_session = BrowserSession(
	browser_profile=BrowserProfile(downloads_path=str(agent_dir / 'downloads')),
)

task = """
Go to https://abc.xyz/assets/cc/27/3ada14014efbadd7a58472f1f3f4/2025q2-alphabet-earnings-release.pdf.
Read the PDF and save 3 interesting data points in "alphabet_earnings.pdf" and share it with me!
""".strip('\n')

agent = Agent(
	task=task,
	llm=llm,
	browser_session=browser_session,
	file_system_path=str(agent_dir / 'fs'),
	flash_mode=True,
)


async def main():
	agent_history = await agent.run()
	input('Press Enter to clean the file system...')
	# clean the file system
	shutil.rmtree(str(agent_dir / 'fs'))


if __name__ == '__main__':
	asyncio.run(main())
