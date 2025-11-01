# Goal: Automates webpage scrolling with various scrolling actions, including element-specific scrolling.

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatOpenAI
from browser_use.browser import BrowserProfile, BrowserSession

if not os.getenv('OPENAI_API_KEY'):
	raise ValueError('OPENAI_API_KEY is not set')

"""
Example: Enhanced 'Scroll' action with page amounts and element-specific scrolling.

This script demonstrates the new enhanced scrolling capabilities:

1. PAGE-LEVEL SCROLLING:
   - Scrolling by specific page amounts using 'num_pages' parameter (0.5, 1.0, 2.0, etc.)
   - Scrolling up or down using the 'down' parameter
   - Uses JavaScript window.scrollBy() or smart container detection

2. ELEMENT-SPECIFIC SCROLLING:
   - NEW: Optional 'index' parameter to scroll within specific elements
   - Perfect for dropdowns, sidebars, and custom UI components
   - Uses direct scrollTop manipulation (no mouse events that might close dropdowns)
   - Automatically finds scroll containers in the element hierarchy
   - Falls back to page scrolling if no container found

3. IMPLEMENTATION DETAILS:
   - Does NOT use mouse movement or wheel events
   - Direct DOM manipulation for precision and reliability
   - Container-aware scrolling prevents unwanted side effects
"""

llm = ChatOpenAI(model='gpt-4.1-mini')

browser_profile = BrowserProfile(headless=False)
browser_session = BrowserSession(browser_profile=browser_profile)

# Example 1: Basic page scrolling with custom amounts
agent1 = Agent(
	task="Navigate to 'https://en.wikipedia.org/wiki/Internet' and scroll down by one page - then scroll up by 0.5 pages - then scroll down by 0.25 pages - then scroll down by 2 pages.",
	llm=llm,
	browser_session=browser_session,
)

# Example 2: Element-specific scrolling (dropdowns and containers)
agent2 = Agent(
	task="""Go to https://semantic-ui.com/modules/dropdown.html#/definition and:
	1. Scroll down in the left sidebar by 2 pages
	2. Then scroll down 1 page in the main content area
	3. Click on the State dropdown and scroll down 1 page INSIDE the dropdown to see more states
	4. The dropdown should stay open while scrolling inside it""",
	llm=llm,
	browser_session=browser_session,
)

# Example 3: Text-based scrolling alternative
agent3 = Agent(
	task="Navigate to 'https://en.wikipedia.org/wiki/Internet' and scroll to the text 'The vast majority of computer'",
	llm=llm,
	browser_session=browser_session,
)


async def main():
	print('Choose which scrolling example to run:')
	print('1. Basic page scrolling with custom amounts (Wikipedia)')
	print('2. Element-specific scrolling (Semantic UI dropdowns)')
	print('3. Text-based scrolling (Wikipedia)')

	choice = input('Enter choice (1-3): ').strip()

	if choice == '1':
		print('🚀 Running Example 1: Basic page scrolling...')
		await agent1.run()
	elif choice == '2':
		print('🚀 Running Example 2: Element-specific scrolling...')
		await agent2.run()
	elif choice == '3':
		print('🚀 Running Example 3: Text-based scrolling...')
		await agent3.run()
	else:
		print('❌ Invalid choice. Running Example 1 by default...')
		await agent1.run()


if __name__ == '__main__':
	asyncio.run(main())
