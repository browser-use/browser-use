"""Harness-backed agent: the browser_use Agent surface over browser-harness.

Same constructor and AgentHistoryList contract as browser_use.Agent; the
engine is the harness daemon driving Chrome over CDP. Needs browser-harness[sdk].

	from browser_use.harness import Agent, Browser
	Agent(task='...', browser=Browser()).run_sync()
"""

from typing import TYPE_CHECKING

_LAZY_IMPORTS = {
	'Agent': ('browser_use.harness.service', 'Agent'),
	'Tools': ('browser_use.harness.tools', 'Tools'),
	'Controller': ('browser_use.harness.tools', 'Controller'),
	'HarnessDomService': ('browser_use.harness.dom', 'HarnessDomService'),
	'HarnessState': ('browser_use.harness.views', 'HarnessState'),
	'HarnessElement': ('browser_use.harness.views', 'HarnessElement'),
	# re-exports so one import path serves both layers
	'Browser': ('browser_harness.sdk', 'Browser'),
	'Element': ('browser_harness.sdk', 'Element'),
	'HarnessError': ('browser_harness.sdk', 'HarnessError'),
	'ActionResult': ('browser_use.agent.views', 'ActionResult'),
	'AgentHistoryList': ('browser_use.agent.views', 'AgentHistoryList'),
}

if TYPE_CHECKING:
	from browser_harness.sdk import Browser, Element, HarnessError

	from browser_use.agent.views import ActionResult, AgentHistoryList
	from browser_use.harness.dom import HarnessDomService
	from browser_use.harness.service import Agent
	from browser_use.harness.tools import Controller, Tools
	from browser_use.harness.views import HarnessElement, HarnessState


def __getattr__(name: str):
	target = _LAZY_IMPORTS.get(name)
	if target is None:
		raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
	module_path, attr = target
	import importlib

	try:
		return getattr(importlib.import_module(module_path), attr)
	except ImportError as e:
		if 'browser_harness' in str(e) or 'pydantic' in str(e):
			raise ImportError(
				'browser_use.harness requires the browser-harness SDK: pip install "browser-harness[sdk]>=0.1.9"'
			) from e
		raise


__all__ = [
	'ActionResult',
	'Agent',
	'AgentHistoryList',
	'Browser',
	'Controller',
	'Element',
	'HarnessDomService',
	'HarnessElement',
	'HarnessError',
	'HarnessState',
	'Tools',
]
