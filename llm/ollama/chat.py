"""Ollama chat model integration for browser-use."""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ChatOllama:
    """Ollama chat model wrapper for browser-use.
    
    This class provides integration with locally running Ollama models,
    ensuring proper host configuration and connection management.
    
    Args:
        model: Name of the Ollama model (e.g., 'llama3.1:8b', 'mistral')
        host: Ollama server URL. Defaults to 'http://127.0.0.1:11434'
        timeout: Request timeout in seconds. Defaults to 180s for local models
        **kwargs: Additional arguments passed to Ollama client
    
    Example:
        >>> from browser_use import Agent
        >>> from browser_use.llm.ollama import ChatOllama
        >>> 
        >>> llm = ChatOllama(model='llama3.1:8b')
        >>> agent = Agent(task='Search for something', llm=llm)
        >>> agent.run_sync()
        
        With custom configuration:
        >>> llm = ChatOllama(
        ...     model='llama3.1:8b',
        ...     host='http://192.168.1.100:11434',  # Remote Ollama server
        ...     timeout=300  # Longer timeout for slower models
        ... )
    
    Note:
        Make sure Ollama is running before using this:
        $ ollama serve
    """
    
    def __init__(
        self,
        model: str,
        host: str = 'http://127.0.0.1:11434',
        timeout: float = 180.0,
        **kwargs: Any
    ):
        """Initialize Ollama chat model with proper host configuration.
        
        Args:
            model: Ollama model name
            host: Ollama server URL (default: http://127.0.0.1:11434)
            timeout: Request timeout in seconds (default: 180)
            **kwargs: Additional Ollama client options
        """
        self.model = model
        self.host = host.rstrip('/')  # Remove trailing slash if present
        self.timeout = timeout
        self.kwargs = kwargs
        self._client: Optional[Any] = None
        
        logger.debug(
            f"Initialized ChatOllama: model={self.model}, host={self.host}, "
            f"timeout={self.timeout}s"
        )
    
    def get_client(self) -> Any:
        """Get or create the Ollama async client.
        
        Returns:
            OllamaAsyncClient instance configured with the correct host
        """
        if self._client is None:
            try:
                from ollama import AsyncClient as OllamaAsyncClient
            except ImportError as e:
                raise ImportError(
                    "Ollama package not installed. Install it with: "
                    "pip install ollama"
                ) from e
            
            # Create client with explicit host configuration
            self._client = OllamaAsyncClient(host=self.host)
            logger.debug(f"Created OllamaAsyncClient with host: {self.host}")
        
        return self._client
    
    async def ainvoke(
        self,
        messages: list[dict[str, str]],
        output_format: Optional[Any] = None
    ) -> dict[str, Any]:
        """Invoke the Ollama model asynchronously.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            output_format: Optional output format specification
            
        Returns:
            Dict containing the model response
            
        Raises:
            ConnectionError: If cannot connect to Ollama server
            TimeoutError: If request exceeds timeout duration
        """
        client = self.get_client()
        
        try:
            logger.debug(
                f"Calling Ollama model '{self.model}' at {self.host} "
                f"with {len(messages)} messages"
            )
            
            # Prepare request options
            options = {'timeout': self.timeout}
            options.update(self.kwargs.get('options', {}))
            
            # Make the request
            response = await client.chat(
                model=self.model,
                messages=messages,
                format=output_format,
                options=options,
                **{k: v for k, v in self.kwargs.items() if k != 'options'}
            )
            
            logger.debug(f"Successfully received response from Ollama")
            return response
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # Connection errors
            if 'connect' in error_msg or 'connection' in error_msg:
                raise ConnectionError(
                    f"Failed to connect to Ollama at {self.host}. "
                    f"Please ensure Ollama is running:\n"
                    f"  1. Start Ollama: ollama serve\n"
                    f"  2. Verify it's running: curl {self.host}/api/tags\n"
                    f"Original error: {e}"
                ) from e
            
            # Timeout errors
            if 'timeout' in error_msg or 'timed out' in error_msg:
                raise TimeoutError(
                    f"Ollama request timed out after {self.timeout}s. "
                    f"Try these solutions:\n"
                    f"  1. Use a faster/smaller model\n"
                    f"  2. Increase timeout: ChatOllama(model='{self.model}', timeout=300)\n"
                    f"  3. Check system resources (CPU/RAM usage)\n"
                    f"Original error: {e}"
                ) from e
            
            # Model not found errors
            if 'not found' in error_msg or '404' in error_msg:
                raise ValueError(
                    f"Model '{self.model}' not found. "
                    f"Pull it first with: ollama pull {self.model}"
                ) from e
            
            # Generic error
            logger.error(f"Ollama request failed: {e}")
            raise
    
    def __repr__(self) -> str:
        """String representation of ChatOllama instance."""
        return (
            f"ChatOllama(model='{self.model}', host='{self.host}', "
            f"timeout={self.timeout})"
        )