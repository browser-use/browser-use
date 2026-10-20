"""Browser Use toolsets for Claude, provided and maintained by Browser Use."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from browser_use.integrations.anthropic import Bash, BrowserUse

__all__ = ['Bash', 'BrowserUse']


def __getattr__(name: str):
	if name not in __all__:
		raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
	from browser_use.integrations import anthropic

	value = getattr(anthropic, name)
	globals()[name] = value
	return value
