"""
Ollama integration for browser-use
"""

from typing import Any, Dict, List, Optional, Union
from langchain_ollama import ChatOllama
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult

class BrowserUseOllama(ChatOllama):
    """
    Wrapper around ChatOllama to support the ainvoke attribute needed by browser-use
    
    This class handles the compatibility between browser-use's token tracking
    and the Pydantic validation in the ChatOllama class
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._ainvoke = self._create_ainvoke()
    
    def _create_ainvoke(self):
        """Create the ainvoke method that will be used by browser-use token tracking"""
        async def ainvoke(messages, output_format=None):
            """Asynchronous invoke method for compatibility with browser-use"""
            return await self.agenerate([messages])
        return ainvoke
    
    @property
    def ainvoke(self):
        """Getter for ainvoke method"""
        return self._ainvoke
    
    @ainvoke.setter
    def ainvoke(self, new_ainvoke):
        """Setter for ainvoke method that bypasses Pydantic validation"""
        self._ainvoke = new_ainvoke
