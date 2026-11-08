from typing import TYPE_CHECKING

from browser_use.browser.browser import Browser

__all__ = ['Browser']

if not TYPE_CHECKING:  # pyright would accept any name imported from here
	from browser_use.legacy import removed_names

	__getattr__ = removed_names(__name__)  # BrowserSession, ProxySettings, ...: the removed error naming the 1.0 answer
