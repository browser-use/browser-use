"""
Test script to verify that the anti-fingerprinting capabilities are working correctly.

This script creates a browser with anti-fingerprinting enabled and navigates to a
fingerprinting test site to check if the browser is detected as a bot.
"""

import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContextConfig


async def test_anti_fingerprint():
    # Create a browser with anti-fingerprinting enabled
    browser = Browser(
        config=BrowserConfig(
            headless=False,
            anti_fingerprint=True  # Enable anti-fingerprinting
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
        
        # Navigate to a fingerprinting test site
        await page.goto('https://bot.sannysoft.com/')
        
        # Wait for the page to load
        await page.wait_for_load_state('networkidle')
        
        # Take a screenshot
        await page.screenshot(path='anti_fingerprint_test.png')
        
        print("Screenshot saved as anti_fingerprint_test.png")
        print("Please check the screenshot to verify that the anti-fingerprinting is working correctly.")
        
        # Wait for user input
        input("Press Enter to close the browser...")
    
    # Close the browser
    await browser.close()


if __name__ == '__main__':
    asyncio.run(test_anti_fingerprint())
