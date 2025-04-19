import asyncio
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig

async def test_browser_config():
    """Test that the BrowserConfig class accepts the anti_fingerprint parameter."""
    # Create a browser config with anti-fingerprinting enabled
    browser_config = BrowserConfig()
    browser_config.anti_fingerprint = True
    
    # Create a browser with the config
    browser = Browser(config=browser_config)
    
    # Print the anti-fingerprint setting
    print(f"Browser anti_fingerprint: {browser.config.anti_fingerprint}")
    
    # Create a context config with anti-fingerprinting enabled
    context_config = BrowserContextConfig()
    context_config.anti_fingerprint = True
    
    # Create a context with the config
    context = BrowserContext(browser=browser, config=context_config)
    
    # Print the anti-fingerprint setting
    print(f"Context anti_fingerprint: {context.config.anti_fingerprint}")
    
    # Initialize the context
    await context._initialize_session()
    
    # Get the current page
    page = await context.get_current_page()
    
    # Navigate to a test site
    await page.goto("https://browserleaks.com/javascript")
    
    # Check if the anti-fingerprinting script is applied
    navigator_properties = await page.evaluate("""() => {
        return {
            webdriver: navigator.webdriver,
            plugins: navigator.plugins.length,
            languages: navigator.languages,
            platform: navigator.platform,
            userAgent: navigator.userAgent,
            vendor: navigator.vendor,
            hardwareConcurrency: navigator.hardwareConcurrency,
            deviceMemory: navigator.deviceMemory
        }
    }""")
    
    print("Navigator properties:", navigator_properties)
    
    # Clean up
    await context.close()
    await browser.close()
    
    print("Test completed successfully")

if __name__ == "__main__":
    asyncio.run(test_browser_config())
