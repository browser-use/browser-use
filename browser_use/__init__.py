import warnings

# Suppress specific deprecation warnings from FAISS
warnings.filterwarnings('ignore', category=DeprecationWarning, module='faiss.loader')
warnings.filterwarnings('ignore', message='builtin type SwigPyPacked has no __module__ attribute')
warnings.filterwarnings('ignore', message='builtin type SwigPyObject has no __module__ attribute')
warnings.filterwarnings('ignore', message='builtin type swigvarlink has no __module__ attribute')

from browser_use.logging_config import setup_logging

setup_logging()

from browser_use.agent.prompts import SystemPrompt
from browser_use.agent.service import Agent
from browser_use.agent.views import ActionModel, ActionResult, AgentHistoryList
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.compat import Browser, BrowserConfig, BrowserContext, BrowserContextConfig
from browser_use.controller.service import Controller
from browser_use.dom.service import DomService

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
