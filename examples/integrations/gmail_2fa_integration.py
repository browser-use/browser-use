"""
Gmail 2FA Integration Example
This example demonstrates how to use the Gmail integration for handling 2FA codes
during web automation. The agent can automatically retrieve verification codes
from Gmail when encountering 2FA requirements.
Setup:
1. Enable Gmail API in Google Cloud Console
2. Create OAuth 2.0 credentials and download JSON
3. Save credentials as ~/.config/browseruse/gmail_credentials.json
4. Run this example - it will guide you through OAuth setup
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

# Add the parent directory to the path so we can import browser_use
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

load_dotenv()

from browser_use import Agent, Controller
from browser_use.integrations.gmail import register_gmail_actions
from browser_use.llm import ChatOpenAI


async def main():
	print('🚀 Gmail 2FA Integration Example')
	print('=' * 50)

	# Initialize controller and register Gmail actions
	controller = Controller()
	register_gmail_actions(controller)

	print('✅ Gmail actions registered with controller')
	print('Available Gmail actions:')
	print('- find_2fa_codes: Find 2FA codes in recent emails')
	print('- poll_for_2fa_code: Wait for new 2FA code from specific sender')
	print('- get_recent_emails: Get recent emails with filtering')
	print('- authenticate_gmail: Authenticate with Gmail API')
	print()

	# Initialize LLM
	llm = ChatOpenAI(model='gpt-4.1')

	# Example 1: Basic Gmail authentication test
	print('📧 Testing Gmail authentication...')
	agent = Agent(task='Authenticate with Gmail API to test the connection', llm=llm, controller=controller)

	try:
		history = await agent.run()
		print('✅ Gmail authentication test completed')
	except Exception as e:
		print(f'❌ Gmail authentication failed: {e}')
		print('\n📝 Setup instructions:')
		print('1. Go to https://console.cloud.google.com/')
		print('2. Create a project and enable Gmail API')
		print('3. Create OAuth 2.0 credentials')
		print('4. Download credentials JSON as ~/.config/browseruse/gmail_credentials.json')
		return

	print('\n' + '=' * 50)

	# Example 2: Find recent 2FA codes
	print('🔍 Testing 2FA code finding...')
	agent2 = Agent(
		task='Find any 2FA verification codes in my recent Gmail emails from the last 30 minutes', llm=llm, controller=controller
	)

	history2 = await agent2.run()
	print('✅ 2FA code search completed')

	print('\n' + '=' * 50)

	# Example 3: Simulate a login flow with 2FA
	print('🌐 Example: Simulated login with 2FA')
	print('This shows how an agent would handle 2FA during login:')

	agent3 = Agent(
		task="""
        Simulate a login flow with 2FA handling:
        1. First check if there are any recent 2FA codes in Gmail
        2. If no codes found, explain that the agent would:
           - Fill in username/password on a login page
           - Click submit
           - When prompted for 2FA, use poll_for_2fa_code to wait for the email
           - Extract the code and enter it on the website
        """,
		llm=llm,
		controller=controller,
	)

	history3 = await agent3.run()
	print('✅ Simulated 2FA flow completed')

	print('\n' + '=' * 50)
	print('🎉 Gmail integration examples completed!')
	print('\n💡 Usage tips:')
	print('- Use find_2fa_codes for checking recent emails')
	print('- Use poll_for_2fa_code when expecting a new 2FA email')
	print('- Specify sender_email to filter by specific services')
	print('- Custom patterns can be added for non-standard codes')


if __name__ == '__main__':
	asyncio.run(main())
