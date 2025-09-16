import asyncio
import os
from pathlib import Path

from browser_use import Agent, BrowserSession
from browser_use.llm.google import ChatGoogle

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# Browser profile directory for persistence (same as main script)
USER_DATA_DIR = Path.home() / '.config' / 'whatsapp_scheduler' / 'browser_profile'
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Storage state file for cookies
STORAGE_STATE_FILE = USER_DATA_DIR / 'storage_state.json'


async def login_to_whatsapp():
	"""Open WhatsApp Web and wait for user to scan QR code"""
	if not GOOGLE_API_KEY:
		print('❌ Error: GOOGLE_API_KEY environment variable is required')
		print("Please set it with: export GOOGLE_API_KEY='your-api-key-here'")
		return

	print('WhatsApp Login Setup')
	print('=' * 50)
	print(f'Browser profile directory: {USER_DATA_DIR}')
	print(f'Storage state file: {STORAGE_STATE_FILE}')
	print('=' * 50)

	try:
		llm = ChatGoogle(model='gemini-2.0-flash-exp', temperature=0.3, api_key=GOOGLE_API_KEY)

		task = """
        You are helping a user log into WhatsApp Web. Follow these steps:
        
        1. Navigate to https://web.whatsapp.com
        2. Wait for the page to load completely
        3. If you see a QR code, tell the user to scan it with their phone
        4. Wait patiently for the login to complete
        5. Once you see the WhatsApp chat interface, confirm successful login
        
        Take your time and be patient with page loads.
        """

		print('\nOpening WhatsApp Web...')
		print('Please scan the QR code when it appears.\n')

		browser_session = BrowserSession(
			headless=False,  # Show browser
			user_data_dir=str(USER_DATA_DIR),  # Use persistent profile directory
			storage_state=str(STORAGE_STATE_FILE) if STORAGE_STATE_FILE.exists() else None,  # Use saved cookies/session
		)

		agent = Agent(task=task, llm=llm, browser_session=browser_session)

		result = await agent.run()

		print('\n✅ Login completed!')
		print("Note: For now, you'll need to scan the QR code each time.")
		print("We'll improve session persistence in a future update.")
		print('\nPress Enter to close the browser...')
		input()

	except Exception as e:
		print(f'\n❌ Error during login: {str(e)}')
		print('Please try again.')


if __name__ == '__main__':
	asyncio.run(login_to_whatsapp())
