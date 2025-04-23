import os
import sys
import platform
import logging
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import argparse

from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SCREENSHOT_DIR = os.path.join(os.path.expanduser("~"), "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

async def take_screenshot(context, name):
    """Take a screenshot and log it"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    page = await context.get_current_page()
    screenshot_path = os.path.join(SCREENSHOT_DIR, f"cross_platform_{name}_{timestamp}.png")
    await page.screenshot(path=screenshot_path)
    logger.info(f"Screenshot saved: {screenshot_path}")
    return screenshot_path

async def test_cross_platform_compatibility(headless=False):
    """Test screenshot functionality across platforms"""
    current_platform = platform.system()
    logger.info(f"Testing on platform: {current_platform}")
    logger.info(f"Home directory: {os.path.expanduser('~')}")
    logger.info(f"Screenshot directory: {SCREENSHOT_DIR}")
    
    if os.path.exists(SCREENSHOT_DIR):
        logger.info(f"✅ Screenshot directory exists: {SCREENSHOT_DIR}")
    else:
        logger.error(f"❌ Screenshot directory does not exist: {SCREENSHOT_DIR}")
        return
    
    extra_browser_args = []
    if current_platform == 'Darwin':  # Mac OS
        logger.info("Detected macOS, adding Mac-specific user agent")
        extra_browser_args.append('--user-agent=' + 
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36')
    
    browser_config = BrowserConfig(
        advanced_mode=True,
        headless=headless,
        extra_browser_args=extra_browser_args
    )
    
    browser = Browser(config=browser_config)
    
    try:
        async with BrowserContext(browser) as context:
            logger.info("Navigating to example.com")
            await context.navigate_to("https://example.com")
            
            screenshot_path = await take_screenshot(context, "example")
            
            if os.path.exists(screenshot_path):
                logger.info(f"✅ Screenshot successfully saved to: {screenshot_path}")
                
                file_size = os.path.getsize(screenshot_path)
                logger.info(f"Screenshot file size: {file_size} bytes")
                
                if file_size > 1000:  # Basic check that it's not empty
                    logger.info("✅ Screenshot has valid file size")
                else:
                    logger.warning("❌ Screenshot file size is suspiciously small")
            else:
                logger.error(f"❌ Failed to save screenshot to: {screenshot_path}")
            
            logger.info("Cross-platform test completed successfully")
            
    except Exception as e:
        logger.error(f"Error during test: {str(e)}")
    finally:
        await browser.close()

async def main():
    parser = argparse.ArgumentParser(description='Test cross-platform screenshot functionality')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    args = parser.parse_args()
    
    await test_cross_platform_compatibility(headless=args.headless)

if __name__ == "__main__":
    asyncio.run(main())
