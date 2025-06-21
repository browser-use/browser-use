from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

Browser = BrowserSession
BrowserConfig = BrowserProfile
BrowserContext = BrowserSession
BrowserContextConfig = BrowserProfile

__all__ = ['Browser', 'BrowserConfig', 'BrowserContext', 'BrowserContextConfig']
