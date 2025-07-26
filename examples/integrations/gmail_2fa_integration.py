"""
Gmail 2FA Integration Example with Grant Mechanism
This example demonstrates how to use the Gmail integration for handling 2FA codes
during web automation with a robust credential grant and re-authentication system.

Features:
- Automatic credential validation and setup
- Interactive OAuth grant flow when credentials are missing/invalid
- Fallback re-authentication mechanisms
- Clear error handling and user guidance

Setup:
1. Enable Gmail API in Google Cloud Console
2. Create OAuth 2.0 credentials and download JSON
3. Save credentials as ~/.config/browseruse/gmail_credentials.json
4. Run this example - it will guide you through OAuth setup if needed
"""

import asyncio
import json
import os
import sys

from dotenv import load_dotenv

# Add the parent directory to the path so we can import browser_use
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

load_dotenv()

from browser_use import Agent, Controller
from browser_use.config import CONFIG
from browser_use.integrations.gmail import GmailService, register_gmail_actions
from browser_use.llm import ChatOpenAI


class GmailGrantManager:
	"""
	Manages Gmail OAuth credential grants and authentication flows.
	Provides a robust mechanism for setting up and maintaining Gmail API access.
	"""

	def __init__(self):
		self.config_dir = CONFIG.BROWSER_USE_CONFIG_DIR
		self.credentials_file = self.config_dir / 'gmail_credentials.json'
		self.token_file = self.config_dir / 'gmail_token.json'
		print(f'GmailGrantManager initialized with config_dir: {self.config_dir}')
		print(f'GmailGrantManager initialized with credentials_file: {self.credentials_file}')
		print(f'GmailGrantManager initialized with token_file: {self.token_file}')

	def check_credentials_exist(self) -> bool:
		"""Check if OAuth credentials file exists."""
		return self.credentials_file.exists()

	def check_token_exists(self) -> bool:
		"""Check if saved token file exists."""
		return self.token_file.exists()

	def validate_credentials_format(self) -> tuple[bool, str]:
		"""
		Validate that the credentials file has the correct format.
		Returns (is_valid, error_message)
		"""
		if not self.check_credentials_exist():
			return False, 'Credentials file not found'

		try:
			with open(self.credentials_file) as f:
				creds = json.load(f)

			required_fields = ['web']
			web = creds['web']
			if not web:
				return False, "Invalid credentials format - missing 'web' section"

			return True, 'Credentials file is valid'

		except json.JSONDecodeError:
			return False, 'Credentials file is not valid JSON'
		except Exception as e:
			return False, f'Error reading credentials file: {e}'

	async def setup_oauth_credentials(self) -> bool:
		"""
		Guide user through OAuth credentials setup process.
		Returns True if setup is successful.
		"""
		print('\n🔐 Gmail OAuth Credentials Setup Required')
		print('=' * 50)

		if not self.check_credentials_exist():
			print('❌ Gmail credentials file not found')
		else:
			is_valid, error = self.validate_credentials_format()
			if not is_valid:
				print(f'❌ Gmail credentials file is invalid: {error}')

		print('\n📋 To set up Gmail API access:')
		print('1. Go to https://console.cloud.google.com/')
		print('2. Create a new project or select an existing one')
		print('3. Enable the Gmail API:')
		print('   - Go to "APIs & Services" > "Library"')
		print('   - Search for "Gmail API" and enable it')
		print('4. Create OAuth 2.0 credentials:')
		print('   - Go to "APIs & Services" > "Credentials"')
		print('   - Click "Create Credentials" > "OAuth client ID"')
		print('   - Choose "Desktop application"')
		print('   - Download the JSON file')
		print(f'5. Save the JSON file as: {self.credentials_file}')
		print(f'6. Ensure the directory exists: {self.config_dir}')

		# Create config directory if it doesn't exist
		self.config_dir.mkdir(parents=True, exist_ok=True)
		print(f'\n✅ Created config directory: {self.config_dir}')

		# Wait for user to set up credentials
		while True:
			user_input = input('\n❓ Have you saved the credentials file? (y/n/skip): ').lower().strip()

			if user_input == 'skip':
				print('⏭️  Skipping credential validation for now')
				return False
			elif user_input == 'y':
				if self.check_credentials_exist():
					is_valid, error = self.validate_credentials_format()
					if is_valid:
						print('✅ Credentials file found and validated!')
						return True
					else:
						print(f'❌ Credentials file is invalid: {error}')
						print('Please check the file format and try again.')
				else:
					print(f'❌ Credentials file still not found at: {self.credentials_file}')
			elif user_input == 'n':
				print('⏳ Please complete the setup steps above and try again.')
			else:
				print('Please enter y, n, or skip')

	async def test_authentication(self, gmail_service: GmailService) -> tuple[bool, str]:
		"""
		Test Gmail authentication and return status.
		Returns (success, message)
		"""
		try:
			print('🔍 Testing Gmail authentication...')
			success = await gmail_service.authenticate()

			if success and gmail_service.is_authenticated():
				print('✅ Gmail authentication successful!')
				return True, 'Authentication successful'
			else:
				return False, 'Authentication failed - invalid credentials or OAuth flow failed'

		except Exception as e:
			return False, f'Authentication error: {e}'

	async def handle_authentication_failure(self, gmail_service: GmailService, error_msg: str) -> bool:
		"""
		Handle authentication failures with fallback mechanisms.
		Returns True if recovery was successful.
		"""
		print(f'\n❌ Gmail authentication failed: {error_msg}')
		print('\n🔧 Attempting recovery...')

		# Option 1: Try removing old token file
		if self.token_file.exists():
			print('🗑️  Removing old token file to force re-authentication...')
			try:
				self.token_file.unlink()
				print('✅ Old token file removed')

				# Try authentication again
				success = await gmail_service.authenticate()
				if success:
					print('✅ Re-authentication successful!')
					return True
			except Exception as e:
				print(f'❌ Failed to remove token file: {e}')

		# Option 2: Validate and potentially re-setup credentials
		is_valid, cred_error = self.validate_credentials_format()
		if not is_valid:
			print(f'\n❌ Credentials file issue: {cred_error}')
			print('🔧 Initiating credential re-setup...')

			return await self.setup_oauth_credentials()

		# Option 3: Provide manual troubleshooting steps
		print('\n🔧 Manual troubleshooting steps:')
		print('1. Check that Gmail API is enabled in Google Cloud Console')
		print('2. Verify OAuth consent screen is configured')
		print('3. Ensure redirect URIs include http://localhost:8080')
		print('4. Check if credentials file is for the correct project')
		print('5. Try regenerating OAuth credentials in Google Cloud Console')

		retry = input('\n❓ Would you like to retry authentication? (y/n): ').lower().strip()
		if retry == 'y':
			success = await gmail_service.authenticate()
			return success

		return False


async def main():
	print('🚀 Gmail 2FA Integration Example with Grant Mechanism')
	print('=' * 60)

	# Initialize grant manager
	grant_manager = GmailGrantManager()

	# Step 1: Check and validate credentials
	print('🔍 Step 1: Validating Gmail credentials...')

	if not grant_manager.check_credentials_exist():
		print('❌ No Gmail credentials found')
		setup_success = await grant_manager.setup_oauth_credentials()
		if not setup_success:
			print('⏹️  Setup cancelled or failed. Exiting...')
			return
	else:
		is_valid, error = grant_manager.validate_credentials_format()
		if not is_valid:
			print(f'❌ Invalid credentials: {error}')
			setup_success = await grant_manager.setup_oauth_credentials()
			if not setup_success:
				print('⏹️  Setup cancelled or failed. Exiting...')
				return
		else:
			print('✅ Gmail credentials file found and validated')

	# Step 2: Initialize Gmail service and test authentication
	print('\n🔍 Step 2: Testing Gmail authentication...')

	gmail_service = GmailService()
	auth_success, auth_message = await grant_manager.test_authentication(gmail_service)

	if not auth_success:
		print(f'❌ Initial authentication failed: {auth_message}')
		recovery_success = await grant_manager.handle_authentication_failure(gmail_service, auth_message)

		if not recovery_success:
			print('❌ Failed to recover Gmail authentication. Please check your setup.')
			return

	# Step 3: Initialize controller with authenticated service
	print('\n🔍 Step 3: Registering Gmail actions...')

	controller = Controller()
	register_gmail_actions(controller, gmail_service=gmail_service)

	print('✅ Gmail actions registered with controller')
	print('Available Gmail actions:')
	print('- get_recent_emails: Get recent emails with filtering')
	print()

	# Initialize LLM
	llm = ChatOpenAI(model='gpt-4.1')

	# Step 4: Test Gmail functionality
	print('🔍 Step 4: Testing Gmail email retrieval...')

	agent = Agent(task='Get recent emails from Gmail to test the integration is working properly', llm=llm, controller=controller)

	try:
		history = await agent.run()
		print('✅ Gmail email retrieval test completed')
	except Exception as e:
		print(f'❌ Gmail email retrieval test failed: {e}')
		# Try one more recovery attempt
		print('🔧 Attempting final recovery...')
		recovery_success = await grant_manager.handle_authentication_failure(gmail_service, str(e))
		if recovery_success:
			print('✅ Recovery successful, re-running test...')
			history = await agent.run()
		else:
			print('❌ Final recovery failed. Please check your Gmail API setup.')
			return

	print('\n' + '=' * 60)

	# Step 5: Demonstrate 2FA code finding
	print('🔍 Step 5: Testing 2FA code detection...')

	agent2 = Agent(
		task='Search for any 2FA verification codes or OTP codes in recent Gmail emails from the last 30 minutes',
		llm=llm,
		controller=controller,
	)

	history2 = await agent2.run()
	print('✅ 2FA code search completed')

	print('\n' + '=' * 60)

	# Step 6: Simulate complete login flow
	print('🔍 Step 6: Demonstrating complete 2FA login flow...')

	agent3 = Agent(
		task="""
		Demonstrate a complete 2FA-enabled login flow:
		1. Check for any existing 2FA codes in recent emails
		2. Explain how the agent would handle a typical login:
		   - Navigate to a login page
		   - Enter credentials
		   - Wait for 2FA prompt
		   - Use get_recent_emails to find the verification code
		   - Extract and enter the 2FA code
		3. Show what types of emails and codes can be detected
		""",
		llm=llm,
		controller=controller,
	)

	history3 = await agent3.run()
	print('✅ Complete 2FA flow demonstration completed')

	print('\n' + '=' * 60)
	print('🎉 Gmail 2FA Integration with Grant Mechanism completed successfully!')
	print('\n💡 Key features demonstrated:')
	print('- ✅ Automatic credential validation and setup')
	print('- ✅ Robust error handling and recovery mechanisms')
	print('- ✅ Interactive OAuth grant flow')
	print('- ✅ Token refresh and re-authentication')
	print('- ✅ 2FA code detection and extraction')
	print('\n🔧 Grant mechanism benefits:')
	print('- Handles missing or invalid credentials gracefully')
	print('- Provides clear setup instructions')
	print('- Automatically recovers from authentication failures')
	print('- Validates credential format before use')
	print('- Offers multiple fallback options')


if __name__ == '__main__':
	asyncio.run(main())
