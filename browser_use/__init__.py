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

from browser_use.legacy import install as _install_0x_import_errors

_install_0x_import_errors()  # import browser_use.dom (any 0.x module path) names its 1.0 answer

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
_BEDROCK = "llm='bedrock:<model id>' (pip install 'pydantic-ai-slim[bedrock]'; AWS credentials and AWS_DEFAULT_REGION)."
_LLM_REMOVED = {  # each 0.x provider class -> its Pydantic AI model string, or ChatOpenAI for an OpenAI-compatible server
	'ChatAzureOpenAI': "llm='azure:<deployment>' with AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY and OPENAI_API_VERSION set.",
	'ChatAWSBedrock': _BEDROCK,
	'ChatAnthropicBedrock': _BEDROCK,
	'ChatDeepSeek': "llm='deepseek:deepseek-chat' with DEEPSEEK_API_KEY set.",
	'ChatGroq': "llm='groq:<model>' (pip install 'pydantic-ai-slim[groq]'; GROQ_API_KEY).",
	'ChatMistral': "llm='mistral:<model>' (pip install 'pydantic-ai-slim[mistral]'; MISTRAL_API_KEY).",
	'ChatOpenRouter': "llm='openrouter:<vendor>/<model>' with OPENROUTER_API_KEY set.",
	'ChatCerebras': "llm='cerebras:<model>' with CEREBRAS_API_KEY set.",
	'ChatVercel': "llm='vercel:<vendor>/<model>' with VERCEL_AI_GATEWAY_API_KEY set.",
	'ChatOllama': "ChatOpenAI('<model>', base_url='http://localhost:11434/v1', api_key='ollama').",
	**dict.fromkeys(
		('ChatLiteLLM', 'ChatOCIRaw', 'ChatOrcaRouter'), 'ChatOpenAI(model, base_url=...) for its OpenAI-compatible endpoint.'
	),
}
_REMOVED = {  # 0.x top-level names -> the 1.0 alternative
	'BrowserSession': 'Browser(...).',
	'BrowserProfile': 'pass options to Browser(...).',
	'BrowserConfig': 'pass options to Browser(...).',
	'BrowserContext': 'pass options to Browser(...).',
	'BrowserContextConfig': 'pass options to Browser(...).',
	'CodeAgent': 'Agent(...): the 1.0 agent writes Python itself.',
	'DomService': 'the agent reads pages with Python.',
	'SystemPrompt': 'Agent(extend_system_message=...).',
	'ActionModel': 'custom actions are plain functions: @tools.action(...).',
	'sandbox': '',
	'models': "a Pydantic AI model string, e.g. llm='openai:gpt-6-luna'.",
	**_LLM_REMOVED,
}


def __getattr__(name: str):
	if name in _LAZY_IMPORTS:
		from importlib import import_module

		attr = getattr(import_module(_LAZY_IMPORTS[name]), name)
		globals()[name] = attr
		return attr
	if name == '__version__':  # 'unknown' from a checkout that is not installed
		from browser_use.utils import get_browser_use_version

		return get_browser_use_version()
	from browser_use.legacy import removed_name

	# BrowserSession, ChatGroq; from browser_use import dom (a 0.x module): the removed error naming the 1.0 answer
	raise removed_name(__name__, name, _REMOVED)


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
