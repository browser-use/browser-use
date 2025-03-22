import asyncio
from playwright.async_api import async_playwright
import os
import sys

from langchain_openai import ChatOpenAI


sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio

from browser_use import Agent
from browser_use.browser.browser import Browser, BrowserConfig, Page
from browser_use.controller.service import Controller


async def ai_action(page: Page, task: str = ''):
	llm = ChatOpenAI(model='gpt-4o')
    
    # This prevents Browser-Use from trying to close the browser context
	config = BrowserConfig(_force_keep_browser_alive = True)
 
    # Waiting for the page to be fully loaded 
	await page.wait_for_load_state("load")
 
    # We'll pass the page as a parameter
	browser = Browser(page=page, config=config)
 
    # And call this method, that will assign the current page's context
	browser_context = await browser.new_context()
	controller = Controller()
	agent = Agent(
		task=task,
		llm=llm,
		controller=controller,
		use_vision=True,
		browser_context=browser_context
	)
	

	history = await agent.run()
	return history.final_result()

"""
    This example will show how to perform a single AI-based action in a Playwright flow.
"""

async def main():
    async with async_playwright() as p:
        # Launch the browser (set headless=False to see the browser window)
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # Navigate to Google's homepage
        await page.goto("https://www.marvel.com/")
        
        # Do a single AI powered action
        await ai_action(page=page, task='Accept cookies')
        
        # Resume playwright flow...
        characters_tab = page.locator("#mvl-flyout-button-2")
        await characters_tab.click()

        # Wait for a few seconds to allow the content to load
        await page.wait_for_timeout(5000)

        # Close the browser
        await browser.close()

# Run the main async function
asyncio.run(main())
