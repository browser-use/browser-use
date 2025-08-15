"""
Action filters (domains) let you limit actions available to the Agent on a step-by-step/page-by-page basis.

@registry.action(..., domains=['*'])
async def some_action(browser_session: BrowserSession):
    ...

This helps prevent the LLM from deciding to use an action that is not compatible with the current page.
It helps limit decision fatigue by scoping actions only to pages where they make sense.
It also helps prevent mis-triggering stateful actions or actions that could break other programs or leak secrets.

For example:
    - only run on certain domains @registry.action(..., domains=['example.com', '*.example.com', 'example.co.*']) (supports globs, but no regex)
    - only fill in a password on a specific login page url
    - only run if this action has not run before on this page (e.g. by looking up the url in a file on disk)

During each step, the agent recalculates the actions available specifically for that page, and informs the LLM.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use.agent.service import Agent, Controller
from browser_use.browser import BrowserSession
from browser_use.llm import ChatOpenAI

# Initialize controller and registry
controller = Controller()
registry = controller.registry


# Action will only be available to Agent on Google domains because of the domain filter
@registry.action(description='Trigger disco mode', domains=['google.com', '*.google.com'])
async def disco_mode(browser_session: BrowserSession):
	# Execute JavaScript using CDP
	cdp_session = await browser_session.get_or_create_cdp_session()
	await cdp_session.cdp_client.send.Runtime.evaluate(
		params={
			'expression': """(() => { 
				// define the wiggle animation
				document.styleSheets[0].insertRule('@keyframes wiggle { 0% { transform: rotate(0deg); } 50% { transform: rotate(10deg); } 100% { transform: rotate(0deg); } }');
				
				document.querySelectorAll("*").forEach(element => {
					element.style.animation = "wiggle 0.5s infinite";
				});
			})()"""
		},
		session_id=cdp_session.session_id,
	)


# Custom filter function that checks URL
async def is_login_page(browser_session: BrowserSession) -> bool:
	"""Check if current page is a login page."""
	try:
		# Get current URL using CDP
		cdp_session = await browser_session.get_or_create_cdp_session()
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'window.location.href', 'returnByValue': True}, session_id=cdp_session.session_id
		)
		url = result.get('result', {}).get('value', '')
		return 'login' in url.lower() or 'signin' in url.lower()
	except Exception:
		return False


# Note: page_filter is not directly supported anymore, so we'll just use domains
# and check the condition inside the function
@registry.action(description='Use the force, luke', domains=['*'])
async def use_the_force(browser_session: BrowserSession):
	# Check if it's a login page
	if not await is_login_page(browser_session):
		return  # Skip if not a login page

	# Execute JavaScript using CDP
	cdp_session = await browser_session.get_or_create_cdp_session()
	await cdp_session.cdp_client.send.Runtime.evaluate(
		params={
			'expression': """(() => { 
				document.querySelector('body').innerHTML = 'These are not the droids you are looking for';
			})()"""
		},
		session_id=cdp_session.session_id,
	)


async def main():
	"""Main function to run the example"""
	browser_session = BrowserSession()
	await browser_session.start()
	llm = ChatOpenAI(model='gpt-4.1')

	# Create the agent
	agent = Agent(  # disco mode will not be triggered on apple.com because the LLM won't be able to see that action available, it should work on Google.com though.
		task="""
            Go to apple.com and trigger disco mode (if dont know how to do that, then just move on).
            Then go to google.com and trigger disco mode.
            After that, go to the Google login page and Use the force, luke.
        """,
		llm=llm,
		browser_session=browser_session,
		controller=controller,
	)

	# Run the agent
	await agent.run(max_steps=10)

	# Cleanup
	await browser_session.kill()


if __name__ == '__main__':
	asyncio.run(main())
