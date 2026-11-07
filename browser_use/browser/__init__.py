from browser_use.browser.browser import Browser

__all__ = ['Browser']


def __getattr__(name: str):
	"""from browser_use.browser import BrowserSession (a 0.x import path): the removal message, not a bare ImportError."""
	from browser_use import _REMOVED

	if name in ('BrowserSession', 'BrowserProfile', 'BrowserConfig'):
		from browser_use.exceptions import removed

		raise ImportError(removed(f'browser_use.browser.{name}', _REMOVED[name]))
	raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
