import os

from onepassword.client import Client

from browser_use import ActionResult, Agent, Browser, ChatOpenAI, Tools
from browser_use.browser.session import BrowserSession

"""
Use Case: Securely log into a website using credentials stored in 1Password vault.
- Use fill_field action to fill in username and password fields with values retrieved from 1Password. The LLM never sees the actual credentials.
- Use blur_page and unblur_page actions to visually obscure sensitive information on the page while filling in credentials for extra security.

**SETUP**
How to setup 1Password with Browser Use
- Get Individual Plan for 1Password
- Go to the Home page and click “New Vault”
    - Add the credentials you need for any websites you want to log into
- Go to “Developer” tab, navigate to “Directory” and create a Service Account
- Give the service account access to the vault
- Copy the Service Account Token and set it as environment variable OP_SERVICE_ACCOUNT_TOKEN
- Install the onepassword package: pip install onepassword-sdk
Note: In this example, we assume that you created a vault named "prod-secrets" and added an item named "X" with fields "username" and "password".
"""


async def main():
	# Gets your service account token from environment variable
	token = os.getenv('OP_SERVICE_ACCOUNT_TOKEN')

	# Authenticate with 1Password
	op_client = await Client.authenticate(auth=token, integration_name='Browser Use Secure Login', integration_version='v1.0.0')

	# Initialize tools
	tools = Tools()

	@tools.registry.action('Apply CSS blur filter to entire page content')
	async def blur_page(browser_session: BrowserSession):
		"""
		Applies CSS blur filter directly to document.body to obscure all page content.
		The blur will remain until unblur_page is called.
		DOM remains accessible for element finding while page is visually blurred.
		"""
		try:
			# Get CDP session
			cdp_session = await browser_session.get_or_create_cdp_session()

			# Apply blur filter to document.body
			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': """
                        (function() {
                            // Check if already blurred
                            if (document.body.getAttribute('data-page-blurred') === 'true') {
                                console.log('[BLUR] Page already blurred');
                                return true;
                            }

                            // Apply CSS blur filter to body
                            document.body.style.filter = 'blur(15px)';
                            document.body.style.webkitFilter = 'blur(15px)'; // Safari support
                            document.body.style.transition = 'filter 0.3s ease';
                            document.body.setAttribute('data-page-blurred', 'true');

                            console.log('[BLUR] Applied CSS blur to page');
                            return true;
                        })();
                    """,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)

			success = result.get('result', {}).get('value', False)
			if success:
				print('[BLUR] Applied CSS blur to page')
				return ActionResult(extracted_content='Successfully applied CSS blur to page', include_in_memory=True)
			else:
				return ActionResult(error='Failed to apply blur', include_in_memory=True)

		except Exception as e:
			print(f'[BLUR ERROR] {e}')
			return ActionResult(error=f'Failed to blur page: {str(e)}', include_in_memory=True)

	@tools.registry.action('Remove CSS blur filter from page')
	async def unblur_page(browser_session: BrowserSession):
		"""
		Removes the CSS blur filter from document.body, restoring normal page visibility.
		"""
		try:
			# Get CDP session
			cdp_session = await browser_session.get_or_create_cdp_session()

			# Remove blur filter from body
			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': """
                        (function() {
                            if (document.body.getAttribute('data-page-blurred') !== 'true') {
                                console.log('[BLUR] Page not blurred');
                                return false;
                            }

                            // Remove CSS blur filter
                            document.body.style.filter = 'none';
                            document.body.style.webkitFilter = 'none';
                            document.body.removeAttribute('data-page-blurred');

                            console.log('[BLUR] Removed CSS blur from page');
                            return true;
                        })();
                    """,
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)

			removed = result.get('result', {}).get('value', False)
			if removed:
				print('[BLUR] Removed CSS blur from page')
				return ActionResult(extracted_content='Successfully removed CSS blur from page', include_in_memory=True)
			else:
				print('[BLUR] Page was not blurred')
				return ActionResult(
					extracted_content='Page was not blurred (may have already been removed)', include_in_memory=True
				)

		except Exception as e:
			print(f'[BLUR ERROR] {e}')
			return ActionResult(error=f'Failed to unblur page: {str(e)}', include_in_memory=True)

	# LLM can call this action to use actors to fill in sensitive fields using 1Password values.
	@tools.registry.action('Fill in a specific field for a website using value from 1Password vault')
	async def fill_field(vault_name: str, item_name: str, field_name: str, browser_session: BrowserSession):
		"""
		Fills in a specific field for a website using the value from 1Password.
		Note: Use blur_page before calling this if you want visual security.
		"""
		try:
			# Resolve field value from 1Password
			field_value = await op_client.secrets.resolve(f'op://{vault_name}/{item_name}/{field_name}')

			# Get current page
			page = await browser_session.must_get_current_page()

			# Find and fill the element
			target_field = await page.must_get_element_by_prompt(f'{field_name} input field', llm)
			await target_field.fill(field_value)

			return ActionResult(
				extracted_content=f'Successfully filled {field_name} field for {vault_name}/{item_name}', include_in_memory=True
			)
		except Exception as e:
			return ActionResult(error=f'Failed to fill {field_name} field: {str(e)}', include_in_memory=True)

	browser_session = Browser()

	llm = ChatOpenAI(model='o3')

	agent = Agent(
		task="""
        Navigate to https://x.com/i/flow/login
        Wait for the page to load.
        Use fill_field action with vault_name='prod-secrets' and item_name='X' and field_name='username'.
        Click the Next button.
        Use fill_field action with vault_name='prod-secrets' and item_name='X' and field_name='password'.
        Click the Log in button.
        Give me the latest 5 tweets from the logged in user's timeline.

        **IMPORTANT** Use blur_page action if you anticipate filling sensitive fields.
        Only use unblur_page action after you see the logged in user's X timeline.
        Your priority is to keep the username and password hidden while filling sensitive fields.
        """,
		browser_session=browser_session,
		llm=llm,
		tools=tools,
		file_system_path='./agent_data',
	)

	await agent.run()


if __name__ == '__main__':
	import asyncio

	asyncio.run(main())
