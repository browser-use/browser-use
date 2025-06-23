"""
Native LLM implementation using openai.types.chat.chat_completion_message_param.

This module provides native implementations for various LLM providers.
"""

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.azure.chat import ChatAzureOpenAI
from browser_use.llm.base import BaseChatModel
from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.groq.chat import ChatGroq
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
from browser_use.llm.openai.chat import ChatOpenAI

# Make better names for the message

__all__ = [
	# Message types
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
	'ChatGoogle',
	'ChatAnthropic',
	'ChatGroq',
	'ChatAzureOpenAI',
]
