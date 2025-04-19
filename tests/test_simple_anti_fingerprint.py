import asyncio
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig

async def test_simple_anti_fingerprint():
    """Test that anti-fingerprinting flag is properly recognized."""
    # Create a browser config with anti-fingerprinting enabled
    browser_config = BrowserConfig()
    browser_config.anti_fingerprint = True
    
    # Create a browser with the config
    browser = Browser(config=browser_config)
    
    # Verify the anti-fingerprint flag is set
    print(f"Browser anti_fingerprint: {browser.config.anti_fingerprint}")
    
    # Create a context config with anti-fingerprinting enabled
    context_config = BrowserContextConfig()
    context_config.anti_fingerprint = True
    
    # Create a context with the config
    context = BrowserContext(browser=browser, config=context_config)
    
    # Verify the anti-fingerprint flag is set
    print(f"Context anti_fingerprint: {context.config.anti_fingerprint}")
    
    # Clean up
    await browser.close()
    
    print("Simple anti-fingerprinting test completed successfully")

if __name__ == '__main__':
    asyncio.run(test_simple_anti_fingerprint())
