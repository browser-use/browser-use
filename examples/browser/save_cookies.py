"""
Export cookies and storage state from your real Chrome browser

This allows you to save your authenticated sessions for later use
without needing to connect to the Chrome profile every time
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Browser


def select_chrome_profile() -> str | None:
	"""Prompt user to select a Chrome profile."""
	profiles = Browser.list_chrome_profiles()
	if not profiles:
		return None

	print('Available Chrome profiles:')
	for i, p in enumerate(profiles, 1):
		print(f'  {i}. {p["name"]}')

	while True:
		choice = input(f'\nSelect profile (1-{len(profiles)}): ').strip()
		if choice.isdigit() and 1 <= int(choice) <= len(profiles):
			return profiles[int(choice) - 1]['directory']
		print('Invalid choice, try again.')


async def main():
	profile = select_chrome_profile()
	browser = Browser.from_system_chrome(profile_directory=profile)

	await browser.start()
	await browser.export_storage_state('storage_state.json')
	await browser.stop()
	print('Storage state exported to storage_state.json')


if __name__ == '__main__':
	asyncio.run(main())
