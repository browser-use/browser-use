# Goal: Demonstrates the hover action for triggering CSS dropdown menus, tooltips, and hover effects.

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

llm = ChatOpenAI(base_url=os.getenv('OPENAI_API_BASE_URL', None), model=os.getenv('LLM_MODEL', 'gpt-4.1-mini'))

browser_profile = BrowserProfile(headless=False)
browser_session = BrowserSession(browser_profile=browser_profile)

# Example 1: Hover over CSS dropdown menu to reveal and select sub-items
agent1 = Agent(
	task="""Go to https://semantic-ui.com/modules/dropdown.html#/definition and:
	1. Find a dropdown menu that requires hovering to reveal sub-items
	2. Hover over the menu trigger to reveal the dropdown
	3. Click on one of the revealed sub-items
	4. Report what item you selected""",
	llm=llm,
	browser_session=browser_session,
)

# Example 2: Hover over tooltips to read hidden content
agent2 = Agent(
	task="""Go to https://getbootstrap.com/docs/5.3/components/tooltips/ and:
	1. Hover over each tooltip button to reveal the tooltip text
	2. Read and report what each tooltip says
	3. Make sure to hover over at least 3 different tooltips""",
	llm=llm,
	browser_session=browser_session,
)

# Example 3: Hover at specific coordinates for precision targeting
agent3 = Agent(
	task="""Navigate to a page with a map or interactive grid, then hover over specific areas
	to reveal information panels or highlights. Use coordinate-based hover when
	element indices are not available for the target area.""",
	llm=llm,
	browser_session=browser_session,
)


async def main():
	print('Choose which hover example to run:')
	print('1. CSS dropdown menu hover (Semantic UI)')
	print('2. Tooltip hover interactions (Bootstrap)')
	print('3. Coordinate-based hover targeting')

	choice = input('Enter choice (1-3): ').strip()

	if choice == '1':
		print('Running Example 1: CSS dropdown menu hover...')
		await agent1.run()
	elif choice == '2':
		print('Running Example 2: Tooltip hover interactions...')
		await agent2.run()
	elif choice == '3':
		print('Running Example 3: Coordinate-based hover targeting...')
		await agent3.run()
	else:
		print('Invalid choice. Running Example 1 by default...')
		await agent1.run()


if __name__ == '__main__':
	asyncio.run(main())
