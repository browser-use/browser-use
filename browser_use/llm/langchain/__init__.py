"""
LangChain compatibility wrapper for browser-use.

This module provides a wrapper to use LangChain-compatible models with browser-use.
"""

from browser_use.llm.langchain.chat import ChatLangchain
from browser_use.llm.langchain.serializer import LangChainMessageSerializer

__all__ = ['ChatLangchain', 'LangChainMessageSerializer']
