"""Browser Use 1.0: a browser agent on Pydantic AI that writes Python against raw CDP.

from browser_use import Agent
result = Agent('Find the top story on Hacker News').run_sync()
print(result.final_result())
"""

import os
from typing import TYPE_CHECKING

os.environ.setdefault('PYDANTIC_AI_NO_BANNER', '1')  # a library should not print an ad on every run

if os.environ.get('BROWSER_USE_SETUP_LOGGING', 'true').lower() != 'false':
	from browser_use.logging_config import setup_logging

	setup_logging()

if TYPE_CHECKING:
	from browser_use.agent import Agent, AgentHistoryList
	from browser_use.browser import Browser
	from browser_use.llm import ChatAnthropic, ChatBrowserUse, ChatGoogle, ChatOpenAI
	from browser_use.tools import ActionResult, Controller, Tools

_LAZY_IMPORTS = {
	'Agent': 'browser_use.agent',
	'AgentHistoryList': 'browser_use.agent',
	'Browser': 'browser_use.browser',
	'Tools': 'browser_use.tools',
	'Controller': 'browser_use.tools',
	'ActionResult': 'browser_use.tools',
	'ChatBrowserUse': 'browser_use.llm',
	'ChatOpenAI': 'browser_use.llm',
	'ChatAnthropic': 'browser_use.llm',
	'ChatGoogle': 'browser_use.llm',
}
_LLM_REMOVED = (
	"a Pydantic AI model string, e.g. llm='groq:llama-3.3-70b-versatile' or 'ollama:qwen3', or ChatOpenAI(model, base_url=...) "
	'for any OpenAI-compatible server.'
)
_REMOVED = {  # 0.x top-level names -> the 1.0 alternative
	'BrowserSession': 'Browser(...).',
	'BrowserProfile': 'pass options to Browser(...).',
	'BrowserConfig': 'pass options to Browser(...).',
	'DomService': 'the agent reads pages with Python.',
	'SystemPrompt': 'Agent(extend_system_message=...).',
	'ActionModel': 'custom actions are plain functions: @tools.action(...).',
	'sandbox': '',
	'models': "a Pydantic AI model string, e.g. llm='openai:gpt-6-luna'.",
	**{
		name: _LLM_REMOVED
		for name in (
			'ChatAnthropicBedrock',
			'ChatAWSBedrock',
			'ChatAzureOpenAI',
			'ChatCerebras',
			'ChatDeepSeek',
			'ChatGroq',
			'ChatLiteLLM',
			'ChatMistral',
			'ChatOCIRaw',
			'ChatOllama',
			'ChatOpenRouter',
			'ChatOrcaRouter',
			'ChatVercel',
		)
	},
}


def __getattr__(name: str):
	if name in _LAZY_IMPORTS:
		from importlib import import_module

		attr = getattr(import_module(_LAZY_IMPORTS[name]), name)
		globals()[name] = attr
		return attr
	if name in _REMOVED:
		from browser_use.exceptions import removed

		raise ImportError(removed(f'browser_use.{name}', _REMOVED[name]))
	raise AttributeError(f"module 'browser_use' has no attribute {name!r}")


__all__ = [
	'Agent',
	'AgentHistoryList',
	'Browser',
	'Tools',
	'Controller',
	'ActionResult',
	'ChatBrowserUse',
	'ChatOpenAI',
	'ChatAnthropic',
	'ChatGoogle',
]
