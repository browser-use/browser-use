import asyncio

from playwright.async_api import async_playwright


async def test_full_screen(start_fullscreen: bool, maximize: bool):
	async with async_playwright() as p:
		try:
			print('Attempting to connect to Chrome...')
			# run in terminal: /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --no-first-run
			browser = await p.chromium.connect_over_cdp(
				'http://localhost:9222',
				timeout=20000,  # 20 second timeout for connection
			)
			print('Connected to Chrome successfully')

			# Get the first context and page, or create new ones if needed
			if len(browser.contexts) == 0:
				context = await browser.new_context(ignore_https_errors=True)
			else:
				context = browser.contexts[0]

			if len(context.pages) == 0:
				page = await context.new_page()
			else:
				page = context.pages[0]

			print('Attempting to navigate to Gmail...')
			try:
				# First try with a shorter timeout
				await page.goto(
					'https://mail.google.com',
					wait_until='load',  # Changed from domcontentloaded
					timeout=10000,
				)
			except Exception as e:
				print(f'First navigation attempt failed: {e}')
				print('Trying again with different settings...')
				# If that fails, try again with different settings
				await page.goto(
					'https://mail.google.com',
					wait_until='commit',  # Less strict wait condition
					timeout=30000,
				)

			# Wait for the page to stabilize
			await asyncio.sleep(2)

			print(f'Current page title: {await page.title()}')

			# Optional: wait for specific Gmail elements
			try:
				await page.wait_for_selector('div[role="main"]', timeout=5000)
				print('Gmail interface detected')
			except Exception as e:
				print(f'Note: Gmail interface not detected: {e}')

			await asyncio.sleep(30)
		except Exception as e:
			print(f'An error occurred: {e}')
			import traceback

			traceback.print_exc()
		finally:
			await browser.close()


if __name__ == '__main__':
	asyncio.run(test_full_screen(False, False))
