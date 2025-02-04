import asyncio
import os

from dotenv import load_dotenv

from browser_use import (
    LLM,
    Agent,
    Browser,
    BrowserConfig,
    BrowserContextConfig,
)

load_dotenv()

llm = LLM(model="openai/gpt-4o")
browser = Browser(
    config=BrowserConfig(
        new_context_config=BrowserContextConfig(save_downloads_path=os.path.join(os.path.expanduser("~"), "downloads"))
    )
)


async def run_download():
    agent = Agent(
        task=('Go to "https://file-examples.com/" and download the smallest doc file.'),
        llm=llm,
        max_actions_per_step=8,
        use_vision=True,
        browser=browser,
    )
    await agent.run(max_steps=25)
    await browser.close()


if __name__ == "__main__":
    asyncio.run(run_download())
