import asyncio
import sys

from browser_use.logging_config import setup_logging

logger = setup_logging()

# Set Windows event loop policy for Playwright compatibility
if sys.platform.startswith('win'):
	try:
		asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
	except Exception as e:
		logger.error(f'❌  Failed to set Windows event loop policy: {type(e).__name__}: {e}')

from browser_use.agent.prompts import SystemPrompt
from browser_use.agent.service import Agent
from browser_use.agent.views import ActionModel, ActionResult, AgentHistoryList
from browser_use.browser import Browser, BrowserConfig, BrowserContext, BrowserContextConfig, BrowserProfile, BrowserSession
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
