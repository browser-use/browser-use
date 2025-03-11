import asyncio
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import Agent
from browser_use.browser.browser import Browser, BrowserConfig, ExtensionConfig

load_dotenv()
api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    raise ValueError('OPENAI_API_KEY is not set')

llm = ChatOpenAI(model='gpt-4o')

browser = Browser(
    config=BrowserConfig(
        extensions=[
            ExtensionConfig(name='ublock-lite', github_url="https://github.com/uBlockOrigin/uBOL-home"),
            ExtensionConfig(name='pdf-viewer', github_url="https://github.com/Rob--W/pdf.js")
        ],
    )
)


async def run_search():
    agent = Agent(
        task=(
            'Go to "https://file-examples.com/" and return the size of the smallest doc file.'
        ),
        llm=llm,
        max_actions_per_step=1,
        browser=browser,
    )

    await agent.run(max_steps=25)


if __name__ == '__main__':
    asyncio.run(run_search())
