"""
Example demonstrating the anti-fingerprinting capabilities of browser-use in a real-world scenario.

This example shows how to:
1. Create a browser with anti-fingerprinting enabled
2. Navigate to a website that uses bot detection
3. Perform actions on the website without being detected as a bot
"""

import asyncio
import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContextConfig

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    # Create a browser with anti-fingerprinting enabled
    browser = Browser(
        config=BrowserConfig(
            headless=False,
            anti_fingerprint=True,  # Enable anti-fingerprinting
            extra_chromium_args=[
                # Additional arguments to further reduce fingerprinting
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-site-isolation-trials',
                '--disable-web-security',
            ]
        )
    )

    # Create a browser context
    async with await browser.new_context(
        config=BrowserContextConfig(
            disable_security=True,
            browser_window_size={'width': 1280, 'height': 800}
        )
    ) as context:
        # Get the current page
        page = await context.get_current_page()

        # Print information about the browser configuration
        logger.info("Browser Configuration:")
        logger.info(f"Anti-fingerprinting: {browser.config.anti_fingerprint}")

        # Navigate to a fingerprinting test site
        logger.info("Navigating to bot.sannysoft.com...")
        await page.goto("https://bot.sannysoft.com/")

        # Wait for the page to load
        await page.wait_for_load_state('networkidle')

        # Take a screenshot
        screenshot_path = "anti_fingerprint_example.png"
        await page.screenshot(path=screenshot_path)
        logger.info(f"Screenshot saved as {screenshot_path}")

        # Wait for user input
        input("Press Enter to close the browser...")

    # Close the browser
    await browser.close()

    input('Press Enter to close...')


if __name__ == '__main__':
    asyncio.run(main())
