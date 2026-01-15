import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from browser_use import Browser

# mock llm to avoid cost
mock_llm = MagicMock()
mock_llm.ainvoke.return_value.completion.action = []
mock_llm.model_name = 'mock'


async def test_har_recording():
	output_dir = Path('./har_test_output')
	output_dir.mkdir(exist_ok=True)
	har_file = output_dir / 'agent_test_session.har'

	if har_file.exists():
		har_file.unlink()

	print(f'HAR file path: {har_file.absolute()}')

	# Configure browser with valid params based on latest codebase if needed
	# User example used Browser(record_har_path=...)
	# We need to verify if BrowserConfig accepts these.

	# Browser is an alias for BrowserSession
	# We need to check if BrowserSession accepts record_har_path directly or via config
	# Based on the user report, they pass it to __init__

	# BrowserSession accepts record_har_path in __init__
	try:
		browser = Browser(headless=True, record_har_path=str(har_file), record_har_mode='full')
	except TypeError as e:
		print(f'Caught unexpected TypeError: {e}')
		return

	async with await browser.new_context() as context:
		page = await context.get_current_page()
		await page.goto('https://www.example.com')
		await asyncio.sleep(2)  # wait for network

	# Check file
	if har_file.exists():
		print(f'✓ HAR file created: {har_file}')
		print(f'Size: {har_file.stat().st_size}')
	else:
		print('✗ HAR file was not created')


if __name__ == '__main__':
	asyncio.run(test_har_recording())
