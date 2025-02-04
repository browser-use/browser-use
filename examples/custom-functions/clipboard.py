import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio

import pyperclip

from browser_use import (
    LLM,
    ActionResult,
    Agent,
    Browser,
    BrowserConfig,
    BrowserContext,
    Controller,
)

browser = Browser(
    config=BrowserConfig(
        headless=False,
    )
)
controller = Controller()


@controller.registry.action("Copy text to clipboard")
def copy_to_clipboard(text: str):
    pyperclip.copy(text)
    return ActionResult(extracted_content=text)


@controller.registry.action("Paste text from clipboard")
async def paste_from_clipboard(browser: BrowserContext):
    text = pyperclip.paste()
    # send text to browser
    page = await browser.get_current_page()
    await page.keyboard.type(text)

    return ActionResult(extracted_content=text)


async def main():
    task = 'Copy the text "Hello, world!" to the clipboard, then go to google.com and paste the text'
    agent = Agent(
        task=task,
        llm=LLM("openai/gpt-4o"),
        controller=controller,
        browser=browser,
    )

    await agent.run()
    await browser.close()

    input("Press Enter to close...")


if __name__ == "__main__":
    asyncio.run(main())
