from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from .bash import Bash
	from .browser_use import BrowserUse

__all__ = ['Bash', 'BrowserUse']


def __getattr__(name: str):
	if name not in __all__:
		raise AttributeError(name)
	try:
		if name == 'Bash':
			from .bash import Bash

			value = Bash
		else:
			from .browser_use import BrowserUse

			value = BrowserUse
	except ModuleNotFoundError as exc:
		if exc.name and (exc.name.startswith('openai') or exc.name.startswith('PIL')):
			raise ImportError('Install browser-use[openai-tools] for the OpenAI browser toolset.') from exc
		raise
	globals()[name] = value
	return value
