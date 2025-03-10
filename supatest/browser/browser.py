from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContextConfig, BrowserContextState

from supatest.browser.context import SupatestBrowserContext


class SupatestBrowser(Browser):
    """Extended version of Browser that uses SupatestBrowserContext"""

    async def new_context(
        self,
        config: BrowserContextConfig = BrowserContextConfig(),
    ) -> SupatestBrowserContext:
        """Override new_context to return SupatestBrowserContext instead of BrowserContext"""
        return SupatestBrowserContext(self, config)

    async def create_context(
        self,
        config: BrowserContextConfig = BrowserContextConfig(),
        state: BrowserContextState | None = None,
    ) -> SupatestBrowserContext:
        """Override create_context to return SupatestBrowserContext instead of BrowserContext"""
        return SupatestBrowserContext(self, config, state) 