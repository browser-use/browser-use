"""Beta Browser Use integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from browser_use.beta.service import Agent, BetaAgentError, find_browser_use_terminal_binary

if TYPE_CHECKING:
	from browser_use.browser import BrowserProfile, BrowserSession
	from browser_use.browser import BrowserSession as Browser
	from browser_use.llm.anthropic.chat import ChatAnthropic
	from browser_use.llm.azure.chat import ChatAzureOpenAI
	from browser_use.llm.browser_use.chat import ChatBrowserUse
	from browser_use.llm.google.chat import ChatGoogle
	from browser_use.llm.groq.chat import ChatGroq
	from browser_use.llm.litellm.chat import ChatLiteLLM
	from browser_use.llm.mistral.chat import ChatMistral
	from browser_use.llm.oci_raw.chat import ChatOCIRaw
	from browser_use.llm.ollama.chat import ChatOllama
	from browser_use.llm.openai.chat import ChatOpenAI
	from browser_use.llm.vercel.chat import ChatVercel

_LAZY_IMPORTS = {
	'Browser': ('browser_use.browser', 'BrowserSession'),
	'BrowserProfile': ('browser_use.browser', 'BrowserProfile'),
	'BrowserSession': ('browser_use.browser', 'BrowserSession'),
	'ChatOpenAI': ('browser_use.llm.openai.chat', 'ChatOpenAI'),
	'ChatGoogle': ('browser_use.llm.google.chat', 'ChatGoogle'),
	'ChatAnthropic': ('browser_use.llm.anthropic.chat', 'ChatAnthropic'),
	'ChatBrowserUse': ('browser_use.llm.browser_use.chat', 'ChatBrowserUse'),
	'ChatGroq': ('browser_use.llm.groq.chat', 'ChatGroq'),
	'ChatLiteLLM': ('browser_use.llm.litellm.chat', 'ChatLiteLLM'),
	'ChatMistral': ('browser_use.llm.mistral.chat', 'ChatMistral'),
	'ChatAzureOpenAI': ('browser_use.llm.azure.chat', 'ChatAzureOpenAI'),
	'ChatOCIRaw': ('browser_use.llm.oci_raw.chat', 'ChatOCIRaw'),
	'ChatOllama': ('browser_use.llm.ollama.chat', 'ChatOllama'),
	'ChatVercel': ('browser_use.llm.vercel.chat', 'ChatVercel'),
}


def __getattr__(name: str):
	if name in _LAZY_IMPORTS:
		module_path, attr_name = _LAZY_IMPORTS[name]
		from importlib import import_module

		module = import_module(module_path)
		attr = getattr(module, attr_name)
		globals()[name] = attr
		return attr
	raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
	'Agent',
	'BetaAgentError',
	'Browser',
	'BrowserProfile',
	'BrowserSession',
	'ChatAnthropic',
	'ChatAzureOpenAI',
	'ChatBrowserUse',
	'ChatGoogle',
	'ChatGroq',
	'ChatLiteLLM',
	'ChatMistral',
	'ChatOCIRaw',
	'ChatOllama',
	'ChatOpenAI',
	'ChatVercel',
	'find_browser_use_terminal_binary',
]
