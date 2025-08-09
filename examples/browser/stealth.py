# pyright: reportMissingImports=false
import asyncio
import os
import shutil
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from imgcat import imgcat

from browser_use.browser import BrowserSession
from browser_use.browser.events import NavigateToUrlEvent
from browser_use.browser.profile import BrowserProfile
from browser_use.llm import ChatOpenAI

llm = ChatOpenAI(model='gpt-4.1')

terminal_width, terminal_height = shutil.get_terminal_size((80, 20))


async def take_screenshot_cdp(browser_session: BrowserSession, filename: str):
	"""Take a screenshot using CDP."""
	# Get current CDP session
	cdp_session = await browser_session.get_or_create_cdp_session()

	# Take screenshot using CDP
	result = await cdp_session.cdp_client.send.Page.captureScreenshot(params={'format': 'png'}, session_id=cdp_session.session_id)

	# Save the screenshot
	import base64

	screenshot_data = base64.b64decode(result['data'])
	Path(filename).write_bytes(screenshot_data)


async def main():
	# Note: Patchright is deprecated, using standard stealth mode

	print('\n\nNORMAL BROWSER:')
	# Default Playwright Chromium Browser
	normal_browser_session = BrowserSession(
		# executable_path=<defaults to playwright builtin browser stored in ms-cache directory>,
		browser_profile=BrowserProfile(
			user_data_dir=None,
			headless=False,
			stealth=False,
			# deterministic_rendering=False,
			# disable_security=False,
		)
	)
	await normal_browser_session.start()

	# Navigate using events
	nav_event = normal_browser_session.event_bus.dispatch(
		NavigateToUrlEvent(url='https://abrahamjuliot.github.io/creepjs/', new_tab=True)
	)
	await nav_event
	await asyncio.sleep(5)

	# Take screenshot using CDP
	await take_screenshot_cdp(normal_browser_session, 'normal_browser.png')
	imgcat(Path('normal_browser.png').read_bytes(), height=max(terminal_height - 15, 40))
	await normal_browser_session.kill()

	print('\n\nSTEALTH BROWSER:')
	stealth_browser_session = BrowserSession(
		# cdp_url='wss://browser.zenrows.com?apikey=your-api-key-here&proxy_region=na',
		#                or try anchor browser, browserless, steel.dev, browserbase, oxylabs, brightdata, etc.
		browser_profile=BrowserProfile(
			user_data_dir='~/.config/browseruse/profiles/stealth',
			stealth=True,
			headless=False,
			disable_security=False,
			deterministic_rendering=False,
		)
	)
	await stealth_browser_session.start()

	# Navigate using events
	nav_event = stealth_browser_session.event_bus.dispatch(
		NavigateToUrlEvent(url='https://abrahamjuliot.github.io/creepjs/', new_tab=True)
	)
	await nav_event
	await asyncio.sleep(5)

	# Take screenshot using CDP
	await take_screenshot_cdp(stealth_browser_session, 'stealth_browser.png')
	imgcat(Path('stealth_browser.png').read_bytes(), height=max(terminal_height - 15, 40))
	await stealth_browser_session.kill()

	# Brave Browser
	if Path('/Applications/Brave Browser.app/Contents/MacOS/Brave Browser').is_file():
		print('\n\nBRAVE BROWSER:')
		brave_browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				executable_path='/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
				headless=False,
				disable_security=False,
				user_data_dir='~/.config/browseruse/profiles/brave',
				deterministic_rendering=False,
			)
		)
		await brave_browser_session.start()

		# Navigate using events
		nav_event = brave_browser_session.event_bus.dispatch(
			NavigateToUrlEvent(url='https://abrahamjuliot.github.io/creepjs/', new_tab=True)
		)
		await nav_event
		await asyncio.sleep(5)

		# Take screenshot using CDP
		await take_screenshot_cdp(brave_browser_session, 'brave_browser.png')
		imgcat(Path('brave_browser.png').read_bytes(), height=max(terminal_height - 15, 40))
		await brave_browser_session.kill()

	if Path('/Applications/Brave Browser.app/Contents/MacOS/Brave Browser').is_file():
		print('\n\nBRAVE + STEALTH BROWSER:')
		brave_stealth_browser_session = BrowserSession(
			browser_profile=BrowserProfile(
				executable_path='/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
				headless=False,
				stealth=True,  # Enable stealth mode
				disable_security=False,
				user_data_dir=None,
				deterministic_rendering=False,
			),
			# Device emulation can be done via viewport/user_agent settings
		)
		await brave_stealth_browser_session.start()

		# Navigate using events
		nav_event = brave_stealth_browser_session.event_bus.dispatch(
			NavigateToUrlEvent(url='https://abrahamjuliot.github.io/creepjs/', new_tab=True)
		)
		await nav_event
		await asyncio.sleep(5)

		# Take screenshot using CDP
		await take_screenshot_cdp(brave_stealth_browser_session, 'brave_stealth_browser.png')
		imgcat(Path('brave_stealth_browser.png').read_bytes(), height=max(terminal_height - 15, 40))

		input('Press [Enter] to close the browser...')
		await brave_stealth_browser_session.kill()

	# print()
	# agent = Agent(
	# 	task="""
	#         Go to https://abrahamjuliot.github.io/creepjs/ and verify that the detection score is >50%.
	#     """,
	# 	llm=llm,
	# 	browser_session=browser_session,
	# )
	# await agent.run()

	# input('Press Enter to close the browser...')

	# agent = Agent(
	# 	task="""
	#         Go to https://bot-detector.rebrowser.net/ and verify that all the bot checks are passed.
	#     """,
	# 	llm=llm,
	# 	browser_session=browser_session,
	# )
	# await agent.run()
	# input('Press Enter to continue to the next test...')

	# agent = Agent(
	# 	task="""
	#         Go to https://www.webflow.com/ and verify that the page is not blocked by a bot check.
	#     """,
	# 	llm=llm,
	# 	browser_session=browser_session,
	# )
	# await agent.run()
	# input('Press Enter to continue to the next test...')

	# agent = Agent(
	# 	task="""
	#         Go to https://www.okta.com/ and verify that the page is not blocked by a bot check.
	#     """,
	# 	llm=llm,
	# 	browser_session=browser_session,
	# )
	# await agent.run()

	# agent = Agent(
	# 	task="""
	#         Go to https://nowsecure.nl/ check the "I'm not a robot" checkbox.
	#     """,
	# 	llm=llm,
	# 	browser_session=browser_session,
	# )
	# await agent.run()

	# input('Press Enter to close the browser...')


if __name__ == '__main__':
	asyncio.run(main())
