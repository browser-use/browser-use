"""
Browser abstraction for Playwright powered by LLMs.
"""

# New API (use these moving forward)
# Legacy API (for backward compatibility)
from .compat import Browser, BrowserConfig, BrowserContext, BrowserContextConfig
from .session import BrowserSession
from .types import BrowserProfile

__all__ = ['Browser', 'BrowserConfig', 'BrowserContext', 'BrowserContextConfig', 'BrowserSession', 'BrowserProfile']
