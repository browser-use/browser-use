"""
Example demonstrating OmniParser integration for enhanced CAPTCHA detection.

This example shows how to configure BrowserUse with OmniParser to improve
the detection of complex UI elements, especially CAPTCHAs.
"""

import asyncio
import logging
import sys
import os

# Add root to path to run as a script
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContextConfig
from browser_use.browser.config import BrowserExtractionConfig
from browser_use.omniparser.views import OmniParserSettings

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Run the example."""
    # Create a browser
    browser = Browser()
    await browser._init()

    # Configure browser with OmniParser integration enabled
    context_config = BrowserContextConfig(
        # Configure extraction with OmniParser
        extraction_config=BrowserExtractionConfig(
            # Enable hybrid extraction (combining DOM and OmniParser)
            use_hybrid_extraction=True,
            # Configure OmniParser settings
            omniparser=OmniParserSettings(
                enabled=True,                 # Enable OmniParser
                confidence_threshold=0.5,     # Minimum confidence for detection
                captcha_detection=True,       # Enable specialized CAPTCHA detection
                merge_with_dom=True,          # Combine DOM and OmniParser results
                prefer_over_dom=False,        # Whether to prefer OmniParser over DOM
                use_api=True                  # Use the hosted API if local installation is not available
            )
        )
    )

    # Create a browser context with the config
    context = await browser.new_context(config=context_config)

    try:
        # Navigate to a page with CAPTCHA
        # For this example, we're using Google's reCAPTCHA demo
        logger.info("Navigating to page with CAPTCHA...")
        page = await context.get_current_page()
        await page.goto("https://www.google.com/recaptcha/api2/demo")

        # Get the current DOM state
        state = await context.get_state()
        
        # Print detected elements with CAPTCHA attributes
        logger.info("Detected elements:")
        
        def print_captcha_elements(element, indent=0):
            """Recursively print elements with CAPTCHA attributes."""
            # Check if it's a DOM element with attributes (not text node)
            if hasattr(element, 'attributes') and element.attributes:
                if "data-captcha" in element.attributes:
                    logger.info(
                        "%sCAPTCHA Element: %s (confidence: %s)",
                        " " * indent,
                        element.tagname,
                        element.attributes.get("data-captcha-confidence", "unknown")
                    )
            
            # Check for children and recursively process
            if hasattr(element, 'children') and element.children:
                for child in element.children:
                    print_captcha_elements(child, indent + 2)
        
        # Process the DOM tree to find CAPTCHA elements
        if hasattr(state, 'element_tree'):
            print_captcha_elements(state.element_tree)
        
        # Take a screenshot for visual verification
        screenshot_base64 = await context.take_screenshot(full_page=True)
        
        # Save the screenshot
        import base64
        with open("captcha_detected.png", "wb") as f:
            f.write(base64.b64decode(screenshot_base64))
        logger.info("Screenshot saved to captcha_detected.png")
        
        # Wait for user to see the results
        await asyncio.sleep(5)

    finally:
        # Clean up
        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
