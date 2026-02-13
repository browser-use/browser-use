import asyncio
import os

from browser_use.browser.events import NavigateToUrlEvent
from browser_use.browser.session import BrowserSession


async def reproduce():
	print('Reproducing Issue #3068: HAR File Capture')

	har_path = os.path.abspath('test_capture.har')
	if os.path.exists(har_path):
		os.remove(har_path)

	print(f'Target HAR path: {har_path}')

	# Initialize session with HAR recording enabled
	# We need to pass record_har_path to BrowserSession or BrowserConfig
	# Based on checking session.py lines 207, it takes record_har_path.

	session = BrowserSession(record_har_path=har_path, headless=True)

	try:
		print('Navigating to example.com...')
		await session.event_bus.dispatch(NavigateToUrlEvent(url='https://example.com'))
		await asyncio.sleep(2)
		print('Navigation done. Closing session...')

	finally:
		await session.close()

	# Check result
	if os.path.exists(har_path):
		size = os.path.getsize(har_path)
		print(f'SUCCESS: HAR file created. Size: {size} bytes')
		if size < 100:
			print('WARNING: HAR file seems too small.')
	else:
		print('FAILURE: HAR file was NOT created.')


if __name__ == '__main__':
	asyncio.run(reproduce())
