import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.browser import BrowserProfile
from browser_use.llm import ChatOpenAI

# Initialize the model
llm = ChatOpenAI(
	model='gpt-4o',
	temperature=0.0,
)
# Simple case: the model will see x_name and x_password, but never the actual values.
# sensitive_data = {'x_name': 'my_x_name', 'x_password': 'my_x_password'}

# Advanced case: domain-specific credentials with reusable data
# Define a single credential set that can be reused
company_credentials = {'company_username': 'user@example.com', 'company_password': 'securePassword123'}

# Map the same credentials to multiple domains for secure access control
# Type annotation to satisfy pyright
sensitive_data: dict[str, str | dict[str, str]] = {
	'https://example.com': company_credentials,
	'https://admin.example.com': company_credentials,
	'https://*.example-staging.com': company_credentials,
	'http*://test.example.com': company_credentials,
	# You can also add domain-specific credentials
	'https://*.google.com': {'g_email': 'user@gmail.com', 'g_pass': 'google_password'},
}
# Update task to use one of the credentials above
task = 'Go to example.com and login with company_username and company_password'

# Always set allowed_domains when using sensitive_data for security
from browser_use.browser.session import BrowserSession

browser_session = BrowserSession(
	browser_profile=BrowserProfile(
		allowed_domains=list(sensitive_data.keys())
		+ ['https://*.trusted-partner.com']  # Domain patterns from sensitive_data + additional allowed domains
	)
)

agent = Agent(task=task, llm=llm, sensitive_data=sensitive_data, browser_session=browser_session)


async def main():
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
