"""
Verification script for anti-fingerprinting capabilities.

This script:
1. Creates a browser with anti-fingerprinting enabled
2. Navigates to a fingerprinting test site
3. Takes a screenshot and saves it for manual verification
4. Prints information about the browser configuration
"""

import asyncio
import sys
import os
import logging
from pathlib import Path

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
        
        # Navigate to fingerprinting test sites
        test_sites = [
            "https://bot.sannysoft.com/",
            "https://abrahamjuliot.github.io/creepjs/",
            "https://fingerprintjs.github.io/fingerprintjs/",
        ]
        
        for site in test_sites:
            site_name = site.split("//")[1].split("/")[0]
            logger.info(f"Testing {site_name}...")
            
            # Navigate to the site
            await page.goto(site)
            
            # Wait for the page to load
            await page.wait_for_load_state('networkidle')
            
            # Take a screenshot
            screenshot_path = f"anti_fingerprint_{site_name}.png"
            await page.screenshot(path=screenshot_path)
            logger.info(f"Screenshot saved as {screenshot_path}")
            
            # Wait for user input before proceeding to the next site
            input(f"Press Enter to continue to the next site...")
    
    # Close the browser
    await browser.close()
    
    logger.info("Verification complete!")
    logger.info("Please check the screenshots to verify that the anti-fingerprinting is working correctly.")


if __name__ == '__main__':
    asyncio.run(main())
