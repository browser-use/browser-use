"""
Key features:
1. Browser-Use and Playwright sharing the same Chrome instance via CDP
2. Take actions with Playwright and continue with Browser-Use actions
3. Let the agent call Playwright functions like screenshot or click on selectors
"""

import asyncio
import os
import subprocess
import sys
import tempfile

from pydantic import BaseModel, Field

# Check for required dependencies first - before other imports
try:
	import aiohttp  # type: ignore
	from playwright.async_api import Browser, Page, async_playwright  # type: ignore
except ImportError as e:
	print(f'❌ Missing dependencies for this example: {e}')
	print('This example requires: playwright aiohttp')
	print('Install with: uv add playwright aiohttp')
	print('Also run: playwright install chromium')
	sys.exit(1)

from browser_use import Agent, BrowserSession, ChatOpenAI, Tools
from browser_use.agent.views import ActionResult

# Global Playwright browser instance - shared between custom actions
playwright_browser: Browser | None = None
playwright_page: Page | None = None


# Custom action parameter models
class PlaywrightFillFormAction(BaseModel):
	"""Parameters for Playwright form filling action."""

	customer_name: str = Field(..., description='Customer name to fill')
	phone_number: str = Field(..., description='Phone number to fill')
	email: str = Field(..., description='Email address to fill')
	size_option: str = Field(..., description='Size option (small/medium/large)')


class PlaywrightScreenshotAction(BaseModel):
	"""Parameters for Playwright screenshot action."""

	filename: str = Field(default='playwright_screenshot.png', description='Filename for screenshot')
	quality: int | None = Field(default=None, description='JPEG quality (1-100), only for .jpg/.jpeg files')


class PlaywrightGetTextAction(BaseModel):
	"""Parameters for getting text using Playwright selectors."""

	selector: str = Field(..., description='CSS selector to get text from. Use "title" for page title.')


async def start_chrome_with_debug_port(port: int = 9222):
	"""
	Start Chrome with remote debugging enabled.
	Returns the Chrome process.
	"""
	# Create temporary directory for Chrome user data
	user_data_dir = tempfile.mkdtemp(prefix='chrome_cdp_')

	# Chrome launch command
	chrome_paths = [
		'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',  # macOS
		'/usr/bin/google-chrome',  # Linux
		'/usr/bin/chromium-browser',  # Linux Chromium
		'chrome',  # Windows/PATH
		'chromium',  # Generic
	]

	chrome_exe = None
	for path in chrome_paths:
		if os.path.exists(path) or path in ['chrome', 'chromium']:
			try:
				# Test if executable works
				test_proc = await asyncio.create_subprocess_exec(
					path, '--version', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
				)
				await test_proc.wait()
				chrome_exe = path
				break
			except Exception:
				continue

	if not chrome_exe:
		raise RuntimeError('❌ Chrome not found. Please install Chrome or Chromium.')

	# Chrome command arguments
	cmd = [
		chrome_exe,
		f'--remote-debugging-port={port}',
		f'--user-data-dir={user_data_dir}',
		'--no-first-run',
		'--no-default-browser-check',
		'--disable-extensions',
		'about:blank',  # Start with blank page
	]

	# Start Chrome process
	process = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

	# Wait for Chrome to start and CDP to be ready
	cdp_ready = False
	for _ in range(20):  # 20 second timeout
		try:
			async with aiohttp.ClientSession() as session:
				async with session.get(
					f'http://localhost:{port}/json/version', timeout=aiohttp.ClientTimeout(total=1)
				) as response:
					if response.status == 200:
						cdp_ready = True
						break
		except Exception:
			pass
		await asyncio.sleep(1)

	if not cdp_ready:
		process.terminate()
		raise RuntimeError('❌ Chrome failed to start with CDP')

	return process


async def connect_playwright_to_cdp(cdp_url: str):
	"""
	Connect Playwright to the same Chrome instance Browser-Use is using.
	This enables custom actions to use Playwright functions.
	"""
	global playwright_browser, playwright_page

	playwright = await async_playwright().start()
	playwright_browser = await playwright.chromium.connect_over_cdp(cdp_url)

	# Get or create a page
	if playwright_browser and playwright_browser.contexts and playwright_browser.contexts[0].pages:
		playwright_page = playwright_browser.contexts[0].pages[0]
	elif playwright_browser:
		context = await playwright_browser.new_context()
		playwright_page = await context.new_page()


# Create custom tools that use Playwright functions
tools = Tools()


@tools.registry.action(
	"Fill out a form using Playwright's precise form filling capabilities. This uses Playwright selectors for reliable form interaction.",
	param_model=PlaywrightFillFormAction,
)
async def playwright_fill_form(params: PlaywrightFillFormAction, browser_session: BrowserSession):
	"""
	Custom action that uses Playwright to fill forms with high precision.
	This demonstrates how to create Browser-Use actions that leverage Playwright's capabilities.
	"""
	try:
		if not playwright_page:
			return ActionResult(error='Playwright not connected. Run setup first.')

		# Filling form with Playwright's precise selectors

		# Wait for form to be ready and fill basic fields
		await playwright_page.wait_for_selector('input[name="custname"]', timeout=10000)
		await playwright_page.fill('input[name="custname"]', params.customer_name)
		await playwright_page.fill('input[name="custtel"]', params.phone_number)
		await playwright_page.fill('input[name="custemail"]', params.email)

		# Handle size selection - check if it's a select dropdown or radio buttons
		size_select = playwright_page.locator('select[name="size"]')
		size_radio = playwright_page.locator(f'input[name="size"][value="{params.size_option}"]')

		if await size_select.count() > 0:
			# It's a select dropdown
			await playwright_page.select_option('select[name="size"]', params.size_option)
		elif await size_radio.count() > 0:
			# It's radio buttons
			await playwright_page.check(f'input[name="size"][value="{params.size_option}"]')
		else:
			raise ValueError(f'Could not find size input field for value: {params.size_option}')

		# Get form data to verify it was filled
		form_data = {}
		form_data['name'] = await playwright_page.input_value('input[name="custname"]')
		form_data['phone'] = await playwright_page.input_value('input[name="custtel"]')
		form_data['email'] = await playwright_page.input_value('input[name="custemail"]')

		# Get size value based on input type
		if await size_select.count() > 0:
			form_data['size'] = await playwright_page.input_value('select[name="size"]')
		else:
			# For radio buttons, find the checked one
			checked_radio = playwright_page.locator('input[name="size"]:checked')
			if await checked_radio.count() > 0:
				form_data['size'] = await checked_radio.get_attribute('value')
			else:
				form_data['size'] = 'none selected'

		success_msg = f'✅ Form filled successfully with Playwright: {form_data}'

		return ActionResult(
			extracted_content=success_msg, include_in_memory=True, long_term_memory=f'Filled form with: {form_data}'
		)

	except Exception as e:
		error_msg = f'❌ Playwright form filling failed: {str(e)}'
		return ActionResult(error=error_msg)


@tools.registry.action(
	"Take a screenshot using Playwright's screenshot capabilities with high quality and precision.",
	param_model=PlaywrightScreenshotAction,
)
async def playwright_screenshot(params: PlaywrightScreenshotAction, browser_session: BrowserSession):
	"""
	Custom action that uses Playwright's advanced screenshot features.
	"""
	try:
		if not playwright_page:
			return ActionResult(error='Playwright not connected. Run setup first.')

		# Taking screenshot with Playwright

		# Use Playwright's screenshot with full page capture
		screenshot_kwargs = {'path': params.filename, 'full_page': True}

		# Add quality parameter only for JPEG files
		if params.quality is not None and params.filename.lower().endswith(('.jpg', '.jpeg')):
			screenshot_kwargs['quality'] = params.quality

		await playwright_page.screenshot(**screenshot_kwargs)

		success_msg = f'✅ Screenshot saved as {params.filename} using Playwright'

		return ActionResult(
			extracted_content=success_msg, include_in_memory=True, long_term_memory=f'Screenshot saved: {params.filename}'
		)

	except Exception as e:
		error_msg = f'❌ Playwright screenshot failed: {str(e)}'
		return ActionResult(error=error_msg)


@tools.registry.action(
	"Extract text from elements using Playwright's powerful CSS selectors and XPath support.", param_model=PlaywrightGetTextAction
)
async def playwright_get_text(params: PlaywrightGetTextAction, browser_session: BrowserSession):
	"""
	Custom action that uses Playwright's advanced text extraction with CSS selectors and XPath.
	"""
	try:
		if not playwright_page:
			return ActionResult(error='Playwright not connected. Run setup first.')

		# Extracting text with Playwright selectors

		# Handle special selectors
		if params.selector.lower() == 'title':
			# Use page.title() for title element
			text_content = await playwright_page.title()
			result_data = {
				'selector': 'title',
				'text_content': text_content,
				'inner_text': text_content,
				'tag_name': 'TITLE',
				'is_visible': True,
			}
		else:
			# Use Playwright's robust element selection and text extraction
			element = playwright_page.locator(params.selector).first

			if await element.count() == 0:
				error_msg = f'❌ No element found with selector: {params.selector}'
				return ActionResult(error=error_msg)

			text_content = await element.text_content()
			inner_text = await element.inner_text()

			# Get additional element info
			tag_name = await element.evaluate('el => el.tagName')
			is_visible = await element.is_visible()

			result_data = {
				'selector': params.selector,
				'text_content': text_content,
				'inner_text': inner_text,
				'tag_name': tag_name,
				'is_visible': is_visible,
			}

		success_msg = f'✅ Extracted text using Playwright: {result_data}'

		return ActionResult(
			extracted_content=str(result_data),
			include_in_memory=True,
			long_term_memory=f'Extracted from {params.selector}: {result_data["text_content"]}',
		)

	except Exception as e:
		error_msg = f'❌ Playwright text extraction failed: {str(e)}'
		return ActionResult(error=error_msg)


async def main():
	"""
	Main function demonstrating Browser-Use + Playwright integration with custom actions.
	"""
	print('🚀 Advanced Playwright + Browser-Use Integration with Custom Actions')

	chrome_process = None
	try:
		# Step 1: Start Chrome with CDP debugging
		chrome_process = await start_chrome_with_debug_port()
		cdp_url = 'http://localhost:9222'

		# Step 2: Connect Playwright to the same Chrome instance
		await connect_playwright_to_cdp(cdp_url)

		# Step 3: Create Browser-Use session connected to same Chrome
		browser_session = BrowserSession(cdp_url=cdp_url)

		# Step 4: Create AI agent with our custom Playwright-powered tools
		agent = Agent(
			task="""
			Please help me demonstrate the integration between Browser-Use and Playwright:
			
			1. First, navigate to https://httpbin.org/forms/post
			2. Use the 'playwright_fill_form' action to fill the form with these details:
			   - Customer name: "Alice Johnson"
			   - Phone: "555-9876"
			   - Email: "alice@demo.com"
			   - Size: "large"
			3. Take a screenshot using the 'playwright_screenshot' action and save it as "form_demo.png"
			4. Extract the title of the page using 'playwright_get_text' action with selector "title"
			5. Finally, submit the form and tell me what happened
			
			This demonstrates how Browser-Use AI can orchestrate tasks while using Playwright's precise capabilities for specific operations.
			""",
			llm=ChatOpenAI(model='gpt-4.1-mini'),
			tools=tools,  # Our custom tools with Playwright actions
			browser_session=browser_session,
		)

		print('🎯 Starting AI agent with custom Playwright actions...')

		# Step 5: Run the agent - it will use both Browser-Use actions and our custom Playwright actions
		result = await agent.run()

		# Keep browser open briefly to see results
		print(f'✅ Integration demo completed! Result: {result}')
		await asyncio.sleep(2)  # Brief pause to see results

	except Exception as e:
		print(f'❌ Error: {e}')
		raise

	finally:
		# Clean up resources
		if playwright_browser:
			await playwright_browser.close()

		if chrome_process:
			chrome_process.terminate()
			try:
				await asyncio.wait_for(chrome_process.wait(), 5)
			except TimeoutError:
				chrome_process.kill()

		print('✅ Cleanup complete')


if __name__ == '__main__':
	# Run the advanced integration demo
	asyncio.run(main())
