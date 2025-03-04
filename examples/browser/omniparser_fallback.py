"""
Example demonstrating OmniParser fallback behavior.

This example shows how OmniParser is used only when DOM extraction is insufficient,
testing various scenarios:
1. DOM extraction is sufficient (OmniParser skipped)
2. DOM extraction finds fewer elements than expected (OmniParser used as fallback)
3. Force OmniParser usage by setting use_as_fallback=False
"""

import asyncio
import logging
import sys
import os
from typing import Optional

# Add root to path to run as a script
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContextConfig
from browser_use.browser.config import BrowserExtractionConfig
from browser_use.omniparser.views import OmniParserSettings
from browser_use.dom.views import DOMState

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_extraction(context, url: str, min_expected: int, use_as_fallback: bool = True) -> Optional[DOMState]:
    """Test extraction with specific settings."""
    page = await context.get_current_page()
    await page.goto(url)
    await asyncio.sleep(3)  # Wait for page to load
    
    state = await context.get_state()
    
    interactive_elements = len([
        elem for elem in state.selector_map.values() 
        if elem.is_interactive and elem.is_visible
    ])
    
    logger.info(f"Found {interactive_elements} interactive elements (minimum expected: {min_expected})")
    logger.info(f"OmniParser fallback mode: {'enabled' if use_as_fallback else 'disabled'}")
    
    return state


async def main():
    """Run the OmniParser fallback example."""
    # Create a browser
    browser = Browser()
    await browser._init()

    try:
        # Test Case 1: DOM extraction is sufficient (Airbnb homepage)
        logger.info("\n=== Test Case 1: DOM extraction is sufficient ===")
        context_config = BrowserContextConfig(
            extraction_config=BrowserExtractionConfig(
                use_hybrid_extraction=True,
                omniparser=OmniParserSettings(
                    enabled=True,
                    confidence_threshold=0.5,
                    use_as_fallback=True,
                    min_expected_elements=5,  # Airbnb homepage should have more than this
                    use_api=True,  # Use hosted API since local installation not available
                    merge_with_dom=True,
                    prefer_over_dom=False,
                    captcha_detection=True
                )
            )
        )
        context = await browser.new_context(config=context_config)
        state = await test_extraction(
            context=context,
            url="https://www.airbnb.com",  # Complex page with many elements
            min_expected=5,
            use_as_fallback=True
        )
        await context.close()

        # Test Case 2: DOM extraction insufficient (GitHub trending with high threshold)
        logger.info("\n=== Test Case 2: DOM extraction insufficient ===")
        context_config = BrowserContextConfig(
            extraction_config=BrowserExtractionConfig(
                use_hybrid_extraction=True,
                omniparser=OmniParserSettings(
                    enabled=True,
                    confidence_threshold=0.5,
                    use_as_fallback=True,
                    min_expected_elements=1000,  # Require more elements than typically available
                    use_api=True,  # Use hosted API since local installation not available
                    merge_with_dom=True,
                    prefer_over_dom=False,
                    captcha_detection=True
                )
            )
        )
        context = await browser.new_context(config=context_config)
        state = await test_extraction(
            context=context,
            url="https://github.com/trending",
            min_expected=1000,
            use_as_fallback=True
        )
        await context.close()

        # Test Case 3: Force OmniParser usage (GitHub repository page)
        logger.info("\n=== Test Case 3: Force OmniParser usage ===")
        context_config = BrowserContextConfig(
            extraction_config=BrowserExtractionConfig(
                use_hybrid_extraction=True,
                omniparser=OmniParserSettings(
                    enabled=True,
                    confidence_threshold=0.5,
                    use_as_fallback=False,  # Always use OmniParser
                    min_expected_elements=1,
                    use_api=True,  # Use hosted API since local installation not available
                    merge_with_dom=True,
                    prefer_over_dom=False,
                    captcha_detection=True
                )
            )
        )
        context = await browser.new_context(config=context_config)
        state = await test_extraction(
            context=context,
            url="https://github.com/microsoft/omniparser",
            min_expected=1,
            use_as_fallback=False
        )
        await context.close()

    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main()) 