import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.llm import ChatOpenAI

# video https://preview.screen.studio/share/vuq91Ej8
llm = ChatOpenAI(
	model='gpt-4.1-2025-04-14',
	temperature=0.0,
	seed=47,
)
task = """go to https://en.wikipedia.org/wiki/Banana and click on links on the wikipedia page to go from banna to Reddit. 
You can only click on links. 
You have to click on the links in the order of the path. 
You must follow this links path: Banana → Blossom -> Social_media -> Reddit
First go to https://en.wikipedia.org/wiki/Banana.
Then scroll down until you find the "Blossom" link in the page and click on it.
Then scroll down until you find the "Social_media" link in the page and click on it.
Then scroll down until you find the "Reddit" link in the page and click on it.
You must click on the links in the order of the path.
You cannot use web or page search.
You must save each page content in the file system.
"""


agent = Agent(task=task, llm=llm)


async def main():
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
