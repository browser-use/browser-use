"""
Custom HTTP Headers via a custom Watchdog.

Creates a custom watchdog that listens to TabCreatedEvent and injects
custom HTTP headers into every new tab using Network.setExtraHTTPHeaders.

Note: The CDP EventRegistry only supports one handler per event method,
so registering directly on Target.attachedToTarget would replace the
internal SessionManager handler.  Using the browser-use event system
(TabCreatedEvent) avoids this and fires after the target is fully set up.

Note: Network.setExtraHTTPHeaders is a full replacement (not additive).

Verified by navigating to https://httpbin.org/headers in a new tab.
"""

import asyncio
import os
import sys
from typing import ClassVar

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from bubus import BaseEvent
from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, Browser, ChatBrowserUse
from browser_use.browser.events import AgentFocusChangedEvent, TabCreatedEvent
from browser_use.browser.watchdog_base import BaseWatchdog

CUSTOM_HEADERS = {
	'X-Custom-Auth': 'Bearer my-secret-token',
	'X-Request-Source': 'browser-use-agent',
	'X-Trace-Id': 'example-trace-12345',
}


class CustomHeadersWatchdog(BaseWatchdog):
	"""Injects custom HTTP headers on every new tab and focus change.

	Listens to both TabCreatedEvent (new tabs) and AgentFocusChangedEvent
	(tab switches) because headers are bound to a CDP session, and sessions
	can be recreated on cross-origin navigations or tab switches.
	"""

	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [TabCreatedEvent, AgentFocusChangedEvent]
	EMITS: ClassVar[list[type[BaseEvent]]] = []

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		"""Set extra headers when a new tab is created."""
		try:
			await self.browser_session.set_extra_headers(CUSTOM_HEADERS, target_id=event.target_id)
		except Exception as e:
			self.logger.debug(f'Could not set headers on {event.target_id[:8]}: {e}')

	async def on_AgentFocusChangedEvent(self, event: AgentFocusChangedEvent) -> None:
		"""Re-apply headers when the agent switches to a different tab."""
		try:
			await self.browser_session.set_extra_headers(CUSTOM_HEADERS, target_id=event.target_id)
		except Exception as e:
			self.logger.debug(f'Could not set headers on {event.target_id[:8]}: {e}')


async def main():
	browser = Browser(headless=False)

	# Start the browser so watchdogs are initialized
	await browser.start()

	# Attach our custom watchdog to the browser session
	CustomHeadersWatchdog.model_rebuild()
	headers_watchdog = CustomHeadersWatchdog(event_bus=browser.event_bus, browser_session=browser)
	headers_watchdog.attach_to_session()

	# The watchdog only fires for tabs created AFTER registration.
	# To apply headers to an already-existing tab, call set_extra_headers():
	#
	#   await browser.set_extra_headers(CUSTOM_HEADERS)
	#   await browser.set_extra_headers(CUSTOM_HEADERS, target_id=some_target_id)
	#
	# Keep in mind that setExtraHTTPHeaders is a full replacement – each
	# call overwrites all previously set extra headers on that target.

	# Run the agent – open httpbin.org/headers in a new tab so the
	# watchdog fires and injects the custom headers.
	agent = Agent(
		task=(
			'Open https://httpbin.org/headers in two different tabs and extract the full JSON response. '
			'Look for the custom headers X-Custom-Auth, X-Request-Source, and X-Trace-Id in the output and compare the results.'
		),
		llm=ChatBrowserUse(model='bu-2-0'),
		browser=browser,
	)

	result = await agent.run()
	print(result.final_result())

	await browser.kill()


if __name__ == '__main__':
	asyncio.run(main())
