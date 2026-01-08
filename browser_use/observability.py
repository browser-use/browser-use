# @file purpose: Observability module for browser-use that handles optional tracing integrations with debug mode support
"""
Observability module for browser-use

This module provides observability decorators that optionally integrate with LangSmith or lmnr (Laminar) for tracing.
If tracing SDKs are not installed, it provides no-op wrappers that accept the same parameters.

Features:
- Optional LangSmith and lmnr integration - works with or without the SDKs installed
- Debug mode support - observe_debug only traces when in debug mode
- Full parameter compatibility with existing decorators
- No-op fallbacks when tracing providers are unavailable
"""

import logging
import os
from collections.abc import Callable
from functools import wraps
from typing import Any, Literal, TypeVar, cast

logger = logging.getLogger(__name__)
from dotenv import load_dotenv

load_dotenv()
_VERBOSE_OBSERVABILITY = os.environ.get('BROWSER_USE_VERBOSE_OBSERVABILITY', 'false').lower() == 'true'

# Type definitions
F = TypeVar('F', bound=Callable[..., Any])
SpanType = Literal['DEFAULT', 'LLM', 'TOOL']


# Check if we're in debug mode
def _is_debug_mode() -> bool:
	"""Check if we're in debug mode based on environment variables or logging level."""

	lmnr_debug_mode = os.getenv('LMNR_LOGGING_LEVEL', '').lower()
	if lmnr_debug_mode == 'debug':
		# logger.info('Debug mode is enabled for observability')
		return True
	# logger.info('Debug mode is disabled for observability')
	return False


# Try to import lmnr observe
_LMNR_AVAILABLE = False
_lmnr_observe = None

try:
	from lmnr import observe as _lmnr_observe  # type: ignore

	if _VERBOSE_OBSERVABILITY:
		logger.debug('Lmnr is available for observability')
	_LMNR_AVAILABLE = True
except ImportError:
	if _VERBOSE_OBSERVABILITY:
		logger.debug('Lmnr is not available for observability')
	_LMNR_AVAILABLE = False

_LANGSMITH_AVAILABLE = False
_langsmith_traceable = None
_langsmith_utils = None

try:
	from langsmith.run_helpers import traceable as _langsmith_traceable  # type: ignore
	from langsmith import utils as _langsmith_utils  # type: ignore

	if _VERBOSE_OBSERVABILITY:
		logger.debug('LangSmith tracing is available for observability')
	_LANGSMITH_AVAILABLE = True
except ImportError:
	if _VERBOSE_OBSERVABILITY:
		logger.debug('LangSmith tracing is not available for observability')
	_LANGSMITH_AVAILABLE = False


def _should_use_langsmith() -> bool:
	"""Determine if LangSmith tracing should be used."""
	if not _LANGSMITH_AVAILABLE or not _langsmith_traceable or not _langsmith_utils:
		return False

	try:
		state = _langsmith_utils.tracing_is_enabled()
	except Exception as exc:  # pragma: no cover - defensive logging
		if _VERBOSE_OBSERVABILITY:
			logger.debug('Failed to determine LangSmith tracing status: %s', exc)
		return False

	return bool(state)


def _span_type_to_run_type(span_type: SpanType) -> str:
	"""Map browser-use span types to LangSmith run types."""
	if span_type == 'LLM':
		return 'llm'
	if span_type == 'TOOL':
		return 'tool'
	return 'chain'


def _masked_inputs(_: dict[str, Any]) -> dict[str, Any]:
	"""Hide function inputs when ignore_input=True."""
	return {'inputs_hidden': True}


def _masked_outputs(_: Any) -> dict[str, Any]:
	"""Hide function outputs when ignore_output=True."""
	return {'output_hidden': True}


def _create_langsmith_decorator(**options: Any) -> Callable[[F], F]:
	"""Create a LangSmith decorator with the same signature as observe."""
	run_type = _span_type_to_run_type(options.get('span_type', 'DEFAULT'))
	langsmith_kwargs: dict[str, Any] = {
		'name': options.get('name'),
		'metadata': options.get('metadata'),
		'tags': options.get('tags'),
	}

	if options.get('ignore_input'):
		langsmith_kwargs['process_inputs'] = _masked_inputs
	if options.get('ignore_output'):
		langsmith_kwargs['process_outputs'] = _masked_outputs

	# Remove keys with None values to avoid warnings in langsmith
	langsmith_kwargs = {key: value for key, value in langsmith_kwargs.items() if value is not None}

	return cast(Callable[[F], F], _langsmith_traceable(run_type, **langsmith_kwargs))


def _create_no_op_decorator(
	name: str | None = None,
	ignore_input: bool = False,
	ignore_output: bool = False,
	metadata: dict[str, Any] | None = None,
	**kwargs: Any,
) -> Callable[[F], F]:
	"""Create a no-op decorator that accepts all lmnr observe parameters but does nothing."""
	import asyncio

	def decorator(func: F) -> F:
		if asyncio.iscoroutinefunction(func):

			@wraps(func)
			async def async_wrapper(*args, **kwargs):
				return await func(*args, **kwargs)

			return cast(F, async_wrapper)
		else:

			@wraps(func)
			def sync_wrapper(*args, **kwargs):
				return func(*args, **kwargs)

			return cast(F, sync_wrapper)

	return decorator


def observe(
	name: str | None = None,
	ignore_input: bool = False,
	ignore_output: bool = False,
	metadata: dict[str, Any] | None = None,
	span_type: SpanType = 'DEFAULT',
	**kwargs: Any,
) -> Callable[[F], F]:
	"""
	Observability decorator that traces function execution when lmnr is available.

	This decorator will use lmnr's observe decorator if lmnr is installed,
	otherwise it will be a no-op that accepts the same parameters.

	Args:
	    name: Name of the span/trace
	    ignore_input: Whether to ignore function input parameters in tracing
	    ignore_output: Whether to ignore function output in tracing
	    metadata: Additional metadata to attach to the span
	    **kwargs: Additional parameters passed to lmnr observe

	Returns:
	    Decorated function that may be traced depending on lmnr availability

	Example:
	    @observe(name="my_function", metadata={"version": "1.0"})
	    def my_function(param1, param2):
	        return param1 + param2
	"""
	options = {
		'name': name,
		'ignore_input': ignore_input,
		'ignore_output': ignore_output,
		'metadata': metadata,
		'span_type': span_type,
		'tags': ['observe', 'observe_debug'],  # important: tags need to be created on Laminar first
		**kwargs,
	}

	if _should_use_langsmith():
		return _create_langsmith_decorator(**options)

	if _LMNR_AVAILABLE and _lmnr_observe:
		return cast(Callable[[F], F], _lmnr_observe(**options))

	return _create_no_op_decorator(**options)


def observe_debug(
	name: str | None = None,
	ignore_input: bool = False,
	ignore_output: bool = False,
	metadata: dict[str, Any] | None = None,
	span_type: SpanType = 'DEFAULT',
	**kwargs: Any,
) -> Callable[[F], F]:
	"""
	Debug-only observability decorator that only traces when in debug mode.

	This decorator will use lmnr's observe decorator if both lmnr is installed
	AND we're in debug mode, otherwise it will be a no-op.

	Debug mode is determined by:
	- DEBUG environment variable set to 1/true/yes/on
	- BROWSER_USE_DEBUG environment variable set to 1/true/yes/on
	- Root logging level set to DEBUG or lower

	Args:
	    name: Name of the span/trace
	    ignore_input: Whether to ignore function input parameters in tracing
	    ignore_output: Whether to ignore function output in tracing
	    metadata: Additional metadata to attach to the span
	    **kwargs: Additional parameters passed to lmnr observe

	Returns:
	    Decorated function that may be traced only in debug mode

	Example:
	    @observe_debug(ignore_input=True, ignore_output=True,name="debug_function", metadata={"debug": True})
	    def debug_function(param1, param2):
	        return param1 + param2
	"""
	options = {
		'name': name,
		'ignore_input': ignore_input,
		'ignore_output': ignore_output,
		'metadata': metadata,
		'span_type': span_type,
		'tags': ['observe_debug'],  # important: tags need to be created on Laminar first
		**kwargs,
	}

	if _should_use_langsmith():
		if _is_debug_mode():
			return _create_langsmith_decorator(**options)
		# Debug mode disabled but LangSmith available, so return no-op
		return _create_no_op_decorator(**options)

	if _LMNR_AVAILABLE and _lmnr_observe and _is_debug_mode():
		# Use the real lmnr observe decorator only in debug mode
		return cast(Callable[[F], F], _lmnr_observe(**options))

	# Use no-op decorator (either not in debug mode or tracing backend not available)
	return _create_no_op_decorator(**options)


# Convenience functions for checking availability and debug status
def is_lmnr_available() -> bool:
	"""Check if lmnr is available for tracing."""
	return _LMNR_AVAILABLE


def is_debug_mode() -> bool:
	"""Check if we're currently in debug mode."""
	return _is_debug_mode()


def get_observability_status() -> dict[str, bool]:
	"""Get the current status of observability features."""
	langsmith_enabled = _should_use_langsmith()
	return {
		'lmnr_available': _LMNR_AVAILABLE,
		'langsmith_available': _LANGSMITH_AVAILABLE,
		'langsmith_enabled': langsmith_enabled,
		'debug_mode': _is_debug_mode(),
		'observe_active': _LMNR_AVAILABLE or langsmith_enabled,
		'observe_debug_active': (_LMNR_AVAILABLE or langsmith_enabled) and _is_debug_mode(),
	}
