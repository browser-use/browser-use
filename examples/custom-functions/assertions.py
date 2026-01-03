"""
Custom assertion actions for smoke tests / regression checks.

These are intentionally NOT included in the default `Tools` action set, because they’re mainly useful when you’re
writing deterministic test flows (CI, monitors, scripted checks) and want the agent to fail fast if an expectation
isn’t met.

On failure, these actions return `ActionResult(is_done=True, success=False, ...)` so the run stops immediately.
If you prefer “soft” assertions, return `ActionResult(error=...)` instead.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

import browser_use.tools.assertion_helpers as ah
from browser_use import ChatOpenAI
from browser_use.agent.service import Agent, Tools
from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession

tools = Tools()


@tools.action('Assert that the given text is present on the current page. Fails fast if not.')
async def assert_text_present(
	text: str,
	browser_session: BrowserSession,
	case_sensitive: bool = False,
	partial: bool = True,
):
	summary = await browser_session.get_browser_state_summary(include_screenshot=False)
	page_text = summary.dom_state.llm_representation()
	ok = ah.assert_text_present(page_text, text, case_sensitive=case_sensitive, partial=partial)
	if not ok:
		msg = f'Expected text "{text}" not found on page {summary.url}'
		return ActionResult(is_done=True, success=False, error=msg, long_term_memory=msg)
	success_msg = f'Assertion passed: found text "{text}"'
	return ActionResult(extracted_content=success_msg, include_in_memory=True, long_term_memory=success_msg)


@tools.action('Assert that the given text is absent on the current page. Fails fast if found.')
async def assert_text_absent(
	text: str,
	browser_session: BrowserSession,
	case_sensitive: bool = False,
	partial: bool = True,
):
	summary = await browser_session.get_browser_state_summary(include_screenshot=False)
	page_text = summary.dom_state.llm_representation()
	ok = ah.assert_text_absent(page_text, text, case_sensitive=case_sensitive, partial=partial)
	if not ok:
		msg = f'Unexpected text "{text}" found on page {summary.url}'
		return ActionResult(is_done=True, success=False, error=msg, long_term_memory=msg)
	success_msg = f'Assertion passed: text "{text}" absent'
	return ActionResult(extracted_content=success_msg, include_in_memory=True, long_term_memory=success_msg)


@tools.action('Assert that an element index is visible in the current DOM. Fails fast if not visible.')
async def assert_element_visible(index: int, browser_session: BrowserSession):
	summary = await browser_session.get_browser_state_summary(include_screenshot=False)
	node = summary.dom_state.selector_map.get(index)
	if not ah.is_visible_node(node):
		msg = f'Element index {index} not visible on {summary.url}'
		return ActionResult(is_done=True, success=False, error=msg, long_term_memory=msg)
	success_msg = f'Assertion passed: element {index} is visible'
	return ActionResult(extracted_content=success_msg, include_in_memory=True, long_term_memory=success_msg)


@tools.action('Assert the current URL. Fails fast if it does not match.')
async def assert_url(expected: str, browser_session: BrowserSession, match_mode: str = 'equals'):
	summary = await browser_session.get_browser_state_summary(include_screenshot=False)
	ok = ah.assert_url(summary, expected, match_mode)
	if not ok:
		msg = f'URL assertion failed: expected {match_mode} "{expected}", got "{summary.url}"'
		return ActionResult(is_done=True, success=False, error=msg, long_term_memory=msg)
	success_msg = f'Assertion passed: url {match_mode} {expected}'
	return ActionResult(extracted_content=success_msg, include_in_memory=True, long_term_memory=success_msg)


@tools.action('Assert the current page title. Fails fast if it does not match.')
async def assert_title(expected: str, browser_session: BrowserSession, match_mode: str = 'equals'):
	summary = await browser_session.get_browser_state_summary(include_screenshot=False)
	ok = ah.assert_title(summary, expected, match_mode)
	if not ok:
		msg = f'Title assertion failed: expected {match_mode} "{expected}", got "{summary.title}"'
		return ActionResult(is_done=True, success=False, error=msg, long_term_memory=msg)
	success_msg = f'Assertion passed: title {match_mode} {expected}'
	return ActionResult(extracted_content=success_msg, include_in_memory=True, long_term_memory=success_msg)


async def main():
	browser_session = BrowserSession()
	await browser_session.start()
	llm = ChatOpenAI(model='gpt-4.1-mini', temperature=0)

	agent = Agent(
		task="""
Go to https://example.com.
Assert that the page title contains "Example Domain".
Assert that the text "Example Domain" is present on the page.
Then finish.
""",
		llm=llm,
		browser_session=browser_session,
		tools=tools,
	)

	await agent.run(max_steps=10)
	await browser_session.kill()


if __name__ == '__main__':
	asyncio.run(main())
