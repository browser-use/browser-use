import logging
import time
from functools import wraps
from typing import Any, Callable, Coroutine, ParamSpec, TypeVar
import asyncio
import functools
from contextlib import asynccontextmanager
from typing import Optional, Callable
from browser_use import Agent

logger = logging.getLogger(__name__)


# Define generic type variables for return type and parameters
R = TypeVar('R')
P = ParamSpec('P')


def time_execution_sync(additional_text: str = '') -> Callable[[Callable[P, R]], Callable[P, R]]:
	def decorator(func: Callable[P, R]) -> Callable[P, R]:
		@wraps(func)
		def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
			start_time = time.time()
			result = func(*args, **kwargs)
			execution_time = time.time() - start_time
			logger.debug(f'{additional_text} Execution time: {execution_time:.2f} seconds')
			return result

		return wrapper

	return decorator


def time_execution_async(
	additional_text: str = '',
) -> Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, R]]]:
	def decorator(func: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, Coroutine[Any, Any, R]]:
		@wraps(func)
		async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
			start_time = time.time()
			result = await func(*args, **kwargs)
			execution_time = time.time() - start_time
			logger.debug(f'{additional_text} Execution time: {execution_time:.2f} seconds')
			return result

		return wrapper

	return decorator


def singleton(cls):
	instance = [None]

	def wrapper(*args, **kwargs):
		if instance[0] is None:
			instance[0] = cls(*args, **kwargs)
		return instance[0]

	return wrapper


class BrowserSessionManager:
    @staticmethod
    @asynccontextmanager
    async def manage_browser_session(agent: Agent):
        """Context manager for browser session handling with proper cleanup"""
        try:
            yield agent
        finally:
            if agent and getattr(agent, 'browser', None):
                await agent.browser.close()

def with_error_handling(cleanup_callback: Optional[Callable] = None):
    """Decorator for handling common errors in browser automation scripts"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return asyncio.run(func(*args, **kwargs))
            except KeyboardInterrupt:
                print("\nScript interrupted by user")
            except Exception as e:
                print(f"An error occurred: {str(e)}")
            finally:
                if cleanup_callback:
                    cleanup_callback()
        return wrapper
    return decorator
