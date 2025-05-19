from .driver import Driver


async def get_default_browser(**config):
    # Start Playwright and launch the browser using the driver.py wrapper
    playwright = await Driver("playwright").start()
    browser = await playwright.chromium.launch(**config)
    # Wrap in our abstraction
    return browser
