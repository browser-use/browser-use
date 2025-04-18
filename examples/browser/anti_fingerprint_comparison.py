"""
Example demonstrating the difference between using anti-fingerprinting and not using it.

This example:
1. Creates two browsers - one with anti-fingerprinting enabled and one without
2. Navigates both browsers to a fingerprinting test site
3. Takes screenshots of both browsers for comparison
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
    anti_fingerprint_browser = Browser(
        config=BrowserConfig(
            headless=False,
            anti_fingerprint=True,  # Enable anti-fingerprinting
        )
    )
    
    # Create a browser without anti-fingerprinting
    normal_browser = Browser(
        config=BrowserConfig(
            headless=False,
            anti_fingerprint=False,  # Disable anti-fingerprinting
        )
    )
    
    # Test the anti-fingerprinting browser
    async with await anti_fingerprint_browser.new_context() as anti_fingerprint_context:
        page = await anti_fingerprint_context.get_current_page()
        await page.goto('https://bot.sannysoft.com/')
        await page.wait_for_load_state('networkidle')
        await page.screenshot(path='with_anti_fingerprint.png')
        logger.info("Screenshot saved as with_anti_fingerprint.png")
    
    # Test the normal browser
    async with await normal_browser.new_context() as normal_context:
        page = await normal_context.get_current_page()
        await page.goto('https://bot.sannysoft.com/')
        await page.wait_for_load_state('networkidle')
        await page.screenshot(path='without_anti_fingerprint.png')
        logger.info("Screenshot saved as without_anti_fingerprint.png")
    
    # Close the browsers
    await anti_fingerprint_browser.close()
    await normal_browser.close()
    
    print("\nComparison complete!")
    print("Please check the screenshots to see the difference between using anti-fingerprinting and not using it.")
    print("- with_anti_fingerprint.png: Browser with anti-fingerprinting enabled")
    print("- without_anti_fingerprint.png: Browser without anti-fingerprinting")
    
    input('Press Enter to close...')


if __name__ == '__main__':
    asyncio.run(main())
