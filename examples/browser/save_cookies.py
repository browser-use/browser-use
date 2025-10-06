import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Browser

# Connect to your existing Chrome browser
browser = Browser(
	executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
	user_data_dir='~/Library/Application Support/Google/Chrome',
	profile_directory='Default',
)


async def main():
	await browser.start()
	await browser.export_storage_state('storage_state3.json')


if __name__ == '__main__':
	asyncio.run(main())
