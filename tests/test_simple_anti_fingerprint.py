import asyncio
import pytest
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig

@pytest.mark.asyncio
async def test_simple_anti_fingerprint():
    """Test that anti-fingerprinting flag is properly recognized."""
    # Create a browser config with anti-fingerprinting enabled
    browser_config = BrowserConfig()
    browser_config.anti_fingerprint = True

    # Create a browser with the config
    browser = Browser(config=browser_config)

    # Verify the anti-fingerprint flag is set
    assert browser.config.anti_fingerprint is True, "Browser anti_fingerprint should be True"

    # Create a context config with anti-fingerprinting enabled
    context_config = BrowserContextConfig()
    context_config.anti_fingerprint = True

    # Create a context with the config
    context = BrowserContext(browser=browser, config=context_config)

    # Verify the anti-fingerprint flag is set
    assert context.config.anti_fingerprint is True, "Context anti_fingerprint should be True"

    # Initialize the context to test actual functionality
    await context._initialize_session()

    # Get the current page
    page = await context.get_current_page()

    # Test that basic anti-fingerprinting measures are applied
    navigator_props = await page.evaluate("""() => {
        return {
            webdriver: navigator.webdriver,
            plugins: navigator.plugins.length,
            platform: navigator.platform,
            vendor: navigator.vendor
        }
    }""")

    # Verify the anti-fingerprinting measures are applied
    assert navigator_props['webdriver'] is None, "webdriver should be undefined"
    assert navigator_props['plugins'] > 0, "plugins should be present"
    assert navigator_props['platform'] in ['Win32', 'MacIntel', 'Linux x86_64'], "platform should be set to a common value"
    assert navigator_props['vendor'] == "Google Inc.", "vendor should be set to Google Inc."

    # Clean up
    await context.close()
    await browser.close()

if __name__ == '__main__':
    # When running directly, we need to handle pytest markers manually
    async def run_test():
        try:
            await test_simple_anti_fingerprint()
            print("Test completed successfully!")
        except AssertionError as e:
            print(f"Test failed: {e}")

    asyncio.run(run_test())
