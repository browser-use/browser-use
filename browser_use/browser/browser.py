from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

BrowserConfig = BrowserProfile
BrowserContextConfig = BrowserProfile
Browser = BrowserSession

__all__ = ['BrowserConfig', 'BrowserContextConfig', 'Browser']
