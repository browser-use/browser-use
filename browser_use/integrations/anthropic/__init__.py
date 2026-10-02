"""Anthropic SDK tools backed by Browser Use."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from .bash import Bash
	from .browser_use import BrowserUse

__all__ = ['Bash', 'BrowserUse']


def __getattr__(name: str):
	if name not in __all__:
		raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
	if name == 'Bash':
		from .bash import Bash

		globals()[name] = Bash
		return Bash
	try:
		from .browser_use import BrowserUse
	except ModuleNotFoundError as exc:
		if exc.name in {'anthropic', 'anthropic.tools', 'anthropic.tools.browser'}:
			raise ImportError(
				'Browser Use requires an Anthropic Python SDK release that includes '
				'anthropic.tools.browser and client.beta.messages.tool_runner.'
			) from exc
		raise
	globals()[name] = BrowserUse
	return BrowserUse
