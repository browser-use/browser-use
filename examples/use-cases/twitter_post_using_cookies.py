import asyncio
import os

from dotenv import load_dotenv

from browser_use import (
    LLM,
    Agent,
    Browser,
    BrowserConfig,
    BrowserContext,
    BrowserContextConfig,
)

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY is not set")

llm = LLM(model="gemini/gemini-2.0-flash-exp")


browser = Browser(
    config=BrowserConfig(
        # chrome_instance_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    )
)
file_path = os.path.join(os.path.dirname(__file__), "twitter_cookies.txt")
context = BrowserContext(browser=browser, config=BrowserContextConfig(cookies_file=file_path))


async def run_search():
    agent = Agent(
        browser_context=context,
        task=('go to https://x.com. write a new post with the text "browser-use ftw", and submit it'),
        llm=llm,
        max_actions_per_step=4,
    )
    await agent.run(max_steps=25)
    input("Press Enter to close the browser...")


if __name__ == "__main__":
    asyncio.run(run_search())
