import asyncio
import json
from pathlib import Path

from browser_use import (
	Agent,
	BrowserSession,
)
from browser_use.browser.events import BrowserStartEvent


async def _load_cookies(browser_session: BrowserSession) -> None:
	"""Load the cookies for the browser session from a JSON file"""

	current_dir = Path(__file__).parent
	cookies_file = current_dir / 'cookies.json'

	if not cookies_file.exists():
		await asyncio.to_thread(lambda: cookies_file.write_text(json.dumps([], indent=2)))

	cookies = []
	cookies_data = await asyncio.to_thread(lambda: cookies_file.read_text())
	cookies = json.loads(cookies_data)

	event = browser_session.event_bus.dispatch(BrowserStartEvent())
	await event.event_result(raise_if_any=True, raise_if_none=False)
	await browser_session._cdp_set_cookies(cookies)


async def _save_cookies(browser_session: BrowserSession) -> None:
	"""Save the cookies for the browser session to a JSON file"""

	current_dir = Path(__file__).parent
	cookies_file = current_dir / 'cookies.json'

	cookies = await browser_session._cdp_get_cookies()

	await asyncio.to_thread(lambda: cookies_file.write_text(json.dumps(cookies, indent=2)))


async def main():
	browser_session = BrowserSession()
	await _load_cookies(browser_session)

	agent = Agent(
		task='Visit https://duckduckgo.com and search for "browser-use founders"',
		browser_session=browser_session,
	)

	await agent.run()
	await _save_cookies(browser_session)
	await browser_session.kill()


if __name__ == '__main__':
	asyncio.run(main())
