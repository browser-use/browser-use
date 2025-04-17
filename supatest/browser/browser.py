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
        browser_config = self.config.model_dump() if self.config else {}
        context_config = config.model_dump() if config else {}
        merged_config = {**browser_config, **context_config}
        return SupatestBrowserContext(config=BrowserContextConfig(**merged_config), browser=self)

    async def create_context(
        self,
        config: BrowserContextConfig = BrowserContextConfig(),
        state: BrowserContextState | None = None,
    ) -> SupatestBrowserContext:
        """Override create_context to return SupatestBrowserContext instead of BrowserContext"""
        return SupatestBrowserContext(self, config, state) 