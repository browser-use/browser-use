"""
Action filters (domains and page_filter) let you limit actions available to the Agent on a step-by-step/page-by-page basis.

@registry.action(..., domains=['*'], page_filter=lambda page: return True)
async def some_action(browser: BrowserContext):
    ...

This helps prevent the LLM from deciding to use an action that is not compatible with the current page.
It helps limit decision fatique by scoping actions only to pages where they make sense.
It also helps prevent mis-triggering stateful actions or actions that could break other programs or leak secrets.

For example:
    - only run on certain domains @registry.action(..., domains=['example.com', '*.example.com', 'example.co.*']) (supports globs, but no regex)
    - only fill in a password on a specific login page url
    - only run if this action has not run before on this page (e.g. by looking up the url in a file on disk)

During each step, the agent recalculates the actions available specifically for that page, and informs the LLM.
"""

import asyncio

from langchain_openai import ChatOpenAI
from patchright.async_api import Page

from browser_use.agent.service import Agent, Browser, BrowserContext, Controller

# Initialize controller and registry
controller = Controller()
registry = controller.registry


# Action will only be available to Agent on Google domains because of the domain filter
@registry.action(description='Trigger disco mode', domains=['google.com', '*.google.com'])
async def disco_mode(browser: BrowserContext):
	page = await browser.get_current_page()
	await page.evaluate("""() => { 
        // define the wiggle animation
        document.styleSheets[0].insertRule('@keyframes wiggle { 0% { transform: rotate(0deg); } 50% { transform: rotate(10deg); } 100% { transform: rotate(0deg); } }');
        
        document.querySelectorAll("*").forEach(element => {
            element.style.animation = "wiggle 0.5s infinite";
        });
    }""")


# you can create a custom page filter function that determines if the action should be available for a given page
def is_login_page(page: Page) -> bool:
	return 'login' in page.url.lower() or 'signin' in page.url.lower()


# then use it in the action decorator to limit the action to only be available on pages where the filter returns True
@registry.action(description='Use the force, luke', page_filter=is_login_page)
async def use_the_force(browser: BrowserContext):
	# this will only ever run on pages that matched the filter
	page = await browser.get_current_page()
	assert is_login_page(page)

	await page.evaluate("""() => { document.querySelector('body').innerHTML = 'These are not the droids you are looking for';}""")


async def main():
	"""Main function to run the example"""
	browser = Browser()
	llm = ChatOpenAI(model_name='gpt-4o')

	# Create the agent
	agent = Agent(  # disco mode will not be triggered on apple.com because the LLM won't be able to see that action available, it should work on Google.com though.
		task="""
            Go to apple.com and trigger disco mode (if dont know how to do that, then just move on).
            Then go to google.com and trigger disco mode.
            After that, go to the Google login page and Use the force, luke.
        """,
		llm=llm,
		browser=browser,
		controller=controller,
	)

	# Run the agent
	await agent.run(max_steps=10)

	# Cleanup
	await browser.close()


if __name__ == '__main__':
	asyncio.run(main())
