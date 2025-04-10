import os
import sys

from browser_use.agent.views import ActionResult
from browser_use.browser.views import GroupTabsAction, UngroupTabsAction

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio

from langchain_openai import ChatOpenAI

from browser_use import Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext

# async def group_tabs(self, tab_ids: list[int] , title: str, color: str = "blue"):
#     """Reset the browser session
#     Call this when you don't want to kill the context but just kill the state
#     """
#     # close all tabs and clear cached state
#     page = await self.get_current_page()

#     js = f"""
#         chrome.tabs.group({{ tabIds: {tab_ids} }}, (groupId) => {{
#             chrome.tabGroups.update(groupId, {{
#                 title: "{title}",
#                 color: "{color}"
#             }});
#         }});
#         """

#     await page.evaluate(js)

# async def ungroup_tabs(self, tab_ids: list[int]):
#     """Reset the browser session
#     Call this when you don't want to kill the context but just kill the state
#     """
#     # close all tabs and clear cached state
#     page = await self.get_current_page()

#     js = f"""
#             for (const tabId of {tab_ids}) {{
#                 chrome.tabs.ungroup(tabId);
#             }}
#         """

#     await page.evaluate(js)


# Initialize controller first
browser = Browser(
	config=BrowserConfig(
		headless=False,
		chrome_instance_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
	)
)
controller = Controller()


@controller.action('Visually group browser tabs in Chrome', param_model=GroupTabsAction, requires_browser=True)
async def group_tabs(params: GroupTabsAction, browser: BrowserContext):
	try:
		# Get tab IDs from params
		tab_ids = params.tab_ids
		title = params.title
		color = params.color

		# Call the low-level implementation in BrowserContext
		result = await browser.group_tabs(tab_ids, title, color='red')
		return ActionResult(extracted_content=result, include_in_memory=True)
	except Exception as e:
		return ActionResult(error=f'Failed to group tabs: {str(e)}')


# Register ungroup_tabs action
@controller.action('Remove visual grouping from tabs in Chrome', param_model=UngroupTabsAction, requires_browser=True)
async def ungroup_tabs(params: UngroupTabsAction, browser: BrowserContext):
	try:
		# Get tab IDs from params
		tab_ids = params.tab_ids

		# Call the low-level implementation in BrowserContext
		result = await browser.ungroup_tabs(tab_ids)
		return ActionResult(extracted_content=result, include_in_memory=True)
	except Exception as e:
		return ActionResult(error=f'Failed to ungroup tabs: {str(e)}')


async def main():
	task = 'Group tabs 1 and 2 into a "Research" group, then ungroup them.'

	model = ChatOpenAI(model='gpt-4o')
	agent = Agent(
		task=task,
		llm=model,
		controller=controller,
		browser=browser,
	)

	await agent.run()

	await browser.close()

	input('Press Enter to close...')


if __name__ == '__main__':
	asyncio.run(main())
