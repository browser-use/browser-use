from browser_use.logging_config import setup_logging

logger = setup_logging()

# Monkeypatch BaseSubprocessTransport.__del__ to handle closed event loops gracefully
from asyncio import base_subprocess

from browser_use.agent.prompts import SystemPrompt
from browser_use.agent.service import Agent
from browser_use.agent.views import ActionModel, ActionResult, AgentHistoryList
from browser_use.browser import Browser, BrowserConfig, BrowserContext, BrowserContextConfig, BrowserProfile, BrowserSession
from browser_use.controller.service import Controller
from browser_use.dom.service import DomService

_original_del = base_subprocess.BaseSubprocessTransport.__del__


def _patched_del(self):
	"""Patched __del__ that handles closed event loops without throwing noisy red-herring errors like RuntimeError: Event loop is closed"""
	try:
		# Check if the event loop is closed before calling the original
		if hasattr(self, '_loop') and self._loop and self._loop.is_closed():
			# Event loop is closed, skip cleanup that requires the loop
			return
		_original_del(self)
	except RuntimeError as e:
		if 'Event loop is closed' in str(e):
			# Silently ignore this specific error
			pass
		else:
			raise


base_subprocess.BaseSubprocessTransport.__del__ = _patched_del


__all__ = [
	'Agent',
	'Browser',
	'BrowserConfig',
	'BrowserSession',
	'BrowserProfile',
	'Controller',
	'DomService',
	'SystemPrompt',
	'ActionResult',
	'ActionModel',
	'AgentHistoryList',
	'BrowserContext',
	'BrowserContextConfig',
]
