"""
We have switched all of our code from langchain to openai.types.chat.chat_completion_message_param.

For easier transition we have
"""

from typing import TYPE_CHECKING

# Lightweight imports that are commonly used
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	SystemMessage,
	UserMessage,
)
from browser_use.llm.messages import (
	ContentPartImageParam as ContentImage,
)
from browser_use.llm.messages import (
	ContentPartRefusalParam as ContentRefusal,
)
from browser_use.llm.messages import (
	ContentPartTextParam as ContentText,
)

# Type stubs for lazy imports
if TYPE_CHECKING:
	from browser_use.llm.anthropic.chat import ChatAnthropic
	from browser_use.llm.aws.chat_anthropic import ChatAnthropicBedrock
	from browser_use.llm.aws.chat_bedrock import ChatAWSBedrock
	from browser_use.llm.azure.chat import ChatAzureOpenAI
	from browser_use.llm.deepseek.chat import ChatDeepSeek
	from browser_use.llm.google.chat import ChatGoogle
	from browser_use.llm.groq.chat import ChatGroq
	from browser_use.llm.ollama.chat import ChatOllama
	from browser_use.llm.openai.chat import ChatOpenAI
	from browser_use.llm.openrouter.chat import ChatOpenRouter

# Lazy imports mapping for heavy chat models
_LAZY_IMPORTS = {
	'ChatAnthropic': ('browser_use.llm.anthropic.chat', 'ChatAnthropic'),
	'ChatAnthropicBedrock': ('browser_use.llm.aws.chat_anthropic', 'ChatAnthropicBedrock'),
	'ChatAWSBedrock': ('browser_use.llm.aws.chat_bedrock', 'ChatAWSBedrock'),
	'ChatAzureOpenAI': ('browser_use.llm.azure.chat', 'ChatAzureOpenAI'),
	'ChatDeepSeek': ('browser_use.llm.deepseek.chat', 'ChatDeepSeek'),
	'ChatGoogle': ('browser_use.llm.google.chat', 'ChatGoogle'),
	'ChatGroq': ('browser_use.llm.groq.chat', 'ChatGroq'),
	'ChatOllama': ('browser_use.llm.ollama.chat', 'ChatOllama'),
	'ChatOpenAI': ('browser_use.llm.openai.chat', 'ChatOpenAI'),
	'ChatOpenRouter': ('browser_use.llm.openrouter.chat', 'ChatOpenRouter'),
}


def __getattr__(name: str):
	"""Lazy import mechanism for heavy chat model imports."""
	if name in _LAZY_IMPORTS:
		module_path, attr_name = _LAZY_IMPORTS[name]
		try:
			from importlib import import_module

			module = import_module(module_path)
			attr = getattr(module, attr_name)
			# Cache the imported attribute in the module's globals
			globals()[name] = attr
			return attr
		except ImportError as e:
			raise ImportError(f'Failed to import {name} from {module_path}: {e}') from e

	raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
	# Message types -> for easier transition from langchain
	'BaseMessage',
	'UserMessage',
	'SystemMessage',
	'AssistantMessage',
	# Content parts with better names
	'ContentText',
	'ContentRefusal',
	'ContentImage',
	# Chat models
	'BaseChatModel',
	'ChatOpenAI',
	'ChatDeepSeek',
	'ChatGoogle',
	'ChatAnthropic',
	'ChatAnthropicBedrock',
	'ChatAWSBedrock',
	'ChatGroq',
	'ChatAzureOpenAI',
	'ChatOllama',
	'ChatOpenRouter',
]
