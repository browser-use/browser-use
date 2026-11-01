import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import ActionResult, Agent, ChatOpenAI, Tools

# Zero-auth disposable temporary email client with smart OTP extraction
# Powered by gecici.email (https://gecici.email)
# Install: pip install gecici-email
from gecici import GeciciEmail

gecici = GeciciEmail()
tools = Tools()


@tools.registry.action('Create disposable temporary email address for signups')
def create_disposable_email(prefix: str = 'agent') -> ActionResult:
	try:
		inbox = gecici.create_inbox(prefix=prefix)
		return ActionResult(extracted_content=f'Created disposable email: {inbox.address}')
	except Exception as e:
		return ActionResult(error=f'Failed to create disposable email: {str(e)}')


@tools.registry.action('Wait for incoming verification email and extract 4-8 digit OTP code')
def wait_for_otp_code(email_address: str, timeout_seconds: int = 30) -> ActionResult:
	try:
		otp = gecici.wait_for_otp(address=email_address, timeout=timeout_seconds)
		if otp:
			return ActionResult(extracted_content=f'Extracted OTP verification code: {otp}')
		return ActionResult(error=f'No OTP received on {email_address} within {timeout_seconds}s.')
	except Exception as e:
		return ActionResult(error=f'Error waiting for OTP: {str(e)}')


@tools.registry.action('Wait for incoming verification email and extract account confirmation link')
def wait_for_confirmation_link(email_address: str, timeout_seconds: int = 30) -> ActionResult:
	try:
		link = gecici.wait_for_link(address=email_address, timeout=timeout_seconds)
		if link:
			return ActionResult(extracted_content=f'Extracted confirmation link: {link}')
		return ActionResult(error=f'No confirmation link received on {email_address} within {timeout_seconds}s.')
	except Exception as e:
		return ActionResult(error=f'Error waiting for confirmation link: {str(e)}')


async def main():
	task = (
		'1. Create a disposable email address using create_disposable_email.\n'
		'2. Go to https://example.com/signup and fill the registration form with the disposable email.\n'
		'3. Submit the form to trigger the verification email.\n'
		'4. Call wait_for_otp_code with the email address to extract the verification code.\n'
		'5. Enter the verification code on the page and complete registration.'
	)

	model = ChatOpenAI(model='gpt-4.1-mini')
	agent = Agent(task=task, llm=model, tools=tools)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
