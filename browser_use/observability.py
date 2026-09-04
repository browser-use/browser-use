# @file purpose: Observability module for browser-use that handles optional lmnr integration with debug mode support
"""
Observability module for browser-use

This module provides observability decorators that optionally integrate with lmnr (Laminar) for tracing.
If lmnr is not installed, it provides no-op wrappers that accept the same parameters.

Features:
- Optional lmnr integration - works with or without lmnr installed
- Debug mode support - observe_debug only traces when in debug mode
- Full parameter compatibility with lmnr observe decorator
- No-op fallbacks when lmnr is unavailable
"""

import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import Any, Literal, TypeVar, cast

logger = logging.getLogger(__name__)
from dotenv import load_dotenv

load_dotenv()

# Type definitions
F = TypeVar('F', bound=Callable[..., Any])


# Check if we're in debug mode
def _is_debug_mode() -> bool:
	"""Check if we're in debug mode based on environment variables or logging level."""

	if os.getenv('LMNR_LOGGING_LEVEL', '').lower() == 'debug':
		return True
	# Generic (backend-agnostic) debug flags, matching this function's documented behavior
	for var in ('BROWSER_USE_DEBUG', 'DEBUG'):
		if os.getenv(var, '').strip().lower() in ('1', 'true', 'yes', 'on'):
			return True
	return False


# Try to import lmnr observe
_LMNR_AVAILABLE = False
_lmnr_observe = None

try:
	from lmnr import observe as _lmnr_observe  # type: ignore

	if os.environ.get('BROWSER_USE_VERBOSE_OBSERVABILITY', 'false').lower() == 'true':
		logger.debug('Lmnr is available for observability')
	_LMNR_AVAILABLE = True
except (ImportError, TypeError):
	if os.environ.get('BROWSER_USE_VERBOSE_OBSERVABILITY', 'false').lower() == 'true':
		logger.debug('Lmnr is not available for observability')
	_LMNR_AVAILABLE = False


# Try to import mlflow for tracing (the tracing-only `mlflow-tracing` package is enough)
_MLFLOW_AVAILABLE = False
try:
	import mlflow  # type: ignore  # noqa: F401

	if os.environ.get('BROWSER_USE_VERBOSE_OBSERVABILITY', 'false').lower() == 'true':
		logger.debug('MLflow is available for observability')
	_MLFLOW_AVAILABLE = True
except (ImportError, TypeError):
	if os.environ.get('BROWSER_USE_VERBOSE_OBSERVABILITY', 'false').lower() == 'true':
		logger.debug('MLflow is not available for observability')
	_MLFLOW_AVAILABLE = False


# Map browser-use span types onto MLflow span types (mlflow.entities.SpanType values are plain strings).
_MLFLOW_SPAN_TYPES: dict[str, str] = {'DEFAULT': 'UNKNOWN', 'LLM': 'LLM', 'TOOL': 'TOOL'}


def _select_backend() -> Literal['lmnr', 'mlflow', 'none']:
	"""Pick the tracing backend from BROWSER_USE_TRACING_BACKEND and the installed packages.

	Values: 'auto' (default), 'lmnr', 'mlflow', 'none'. 'auto' prefers lmnr when present
	(preserving historical behavior), then mlflow, then falls back to a no-op.
	"""
	choice = os.getenv('BROWSER_USE_TRACING_BACKEND', 'auto').strip().lower()
	if choice == 'lmnr':
		return 'lmnr' if _LMNR_AVAILABLE else 'none'
	if choice == 'mlflow':
		return 'mlflow' if _MLFLOW_AVAILABLE else 'none'
	if choice == 'none':
		return 'none'
	# 'auto' (or any unknown value): prefer lmnr, then mlflow, else no-op
	if _LMNR_AVAILABLE:
		return 'lmnr'
	if _MLFLOW_AVAILABLE:
		return 'mlflow'
	return 'none'


_TRACING_BACKEND: Literal['lmnr', 'mlflow', 'none'] = _select_backend()


@contextmanager
def _mlflow_span(name: str, span_type: str) -> Iterator[Any]:
	"""Open an MLflow span, yielding it (or None if MLflow can't). Shared by every mlflow branch."""
	try:
		import mlflow

		cm = mlflow.start_span(name=name, span_type=span_type)
	except Exception:
		yield None
		return
	with cm as span:
		yield span


def _create_mlflow_decorator(
	name: str | None = None,
	ignore_input: bool = False,
	ignore_output: bool = False,
	metadata: dict[str, Any] | None = None,
	span_type: Literal['DEFAULT', 'LLM', 'TOOL'] = 'DEFAULT',
	tags: list[str] | None = None,
	**kwargs: Any,
) -> Callable[[F], F]:
	"""Create a decorator that wraps a function in an MLflow span.

	Honors ignore_input/ignore_output (browser-use ignores both on most spans because inputs are
	huge DOM/screenshot blobs). Any tracing failure is swallowed so it never breaks the agent;
	exceptions raised by the wrapped function propagate unchanged (MLflow marks the span errored).
	"""
	assert span_type in _MLFLOW_SPAN_TYPES, f'unexpected span_type {span_type!r}'
	import asyncio

	mlflow_span_type = _MLFLOW_SPAN_TYPES.get(span_type, 'UNKNOWN')

	def _annotate(span: Any, args: tuple, fn_kwargs: dict) -> None:
		try:
			attributes: dict[str, Any] = {}
			if metadata:
				attributes.update(metadata)
			if tags:
				attributes['tags'] = tags
			if attributes:
				span.set_attributes(attributes)
			if not ignore_input:
				span.set_inputs({'args': args, 'kwargs': fn_kwargs})
		except Exception:
			pass

	def decorator(func: F) -> F:
		span_name = name or func.__name__

		if asyncio.iscoroutinefunction(func):

			@wraps(func)
			async def async_wrapper(*args, **fn_kwargs):
				with _mlflow_span(span_name, mlflow_span_type) as span:
					if span is None:
						return await func(*args, **fn_kwargs)
					_annotate(span, args, fn_kwargs)
					result = await func(*args, **fn_kwargs)
					if not ignore_output:
						try:
							span.set_outputs(result)
						except Exception:
							pass
					return result

			return cast(F, async_wrapper)
		else:

			@wraps(func)
			def sync_wrapper(*args, **fn_kwargs):
				with _mlflow_span(span_name, mlflow_span_type) as span:
					if span is None:
						return func(*args, **fn_kwargs)
					_annotate(span, args, fn_kwargs)
					result = func(*args, **fn_kwargs)
					if not ignore_output:
						try:
							span.set_outputs(result)
						except Exception:
							pass
					return result

			return cast(F, sync_wrapper)

	return decorator


@contextmanager
def action_span(name: str, input: Any = None, span_type: str = 'TOOL') -> Iterator[Any]:
	"""Backend-neutral span for a discrete agent action (navigate, click, wait, ...).

	Mirrors observe()'s backend routing but as a context manager, for call sites (e.g. Tools.act)
	that open a span named after a value only known at runtime. Yields the backend span object
	(or None). Any tracing failure is swallowed so it never breaks action execution.
	"""
	if _TRACING_BACKEND == 'mlflow':
		with _mlflow_span(name, _MLFLOW_SPAN_TYPES.get(span_type, span_type)) as span:
			if span is not None:
				try:
					if input is not None:
						span.set_inputs(input)
				except Exception:
					pass
			yield span
		return
	if _TRACING_BACKEND == 'lmnr':
		try:
			from lmnr import Laminar

			with Laminar.start_as_current_span(name=name, input=input, span_type=cast(Any, span_type)) as span:
				yield span
			return
		except Exception:
			yield None
			return
	yield None


@contextmanager
def llm_span(model: str) -> Iterator[Any]:
	"""Model-named LLM span for backends that don't auto-instrument the LLM SDK (e.g. MLflow).

	lmnr already spans LLM calls through its provider instrumentation, so this is a no-op there;
	on MLflow it yields a span named after the model (e.g. 'gemini-2.5-flash'), like Laminar shows,
	instead of leaving the call unnamed. Any tracing failure is swallowed.
	"""
	if _TRACING_BACKEND == 'mlflow':
		with _mlflow_span(model, 'LLM') as span:
			yield span
		return
	yield None


def record_llm(
	span: Any,
	inputs: Any = None,
	output: Any = None,
	usage: Any = None,
	model: str | None = None,
	cost: Any = None,
	provider: str | None = None,
) -> None:
	"""Record an LLM call's messages, output, model, provider, token usage, and cost on an MLflow span.

	Populates the Chat / Inputs-Outputs view and lets MLflow aggregate the trace-level token
	count and cost. Best-effort and backend-agnostic: `usage` exposes prompt_tokens /
	completion_tokens / total_tokens / prompt_cached_tokens and `cost` exposes prompt_cost /
	completion_cost / total_cost (browser-use's ChatInvokeUsage / TokenCostCalculated). No-op if
	span is None or the active backend isn't MLflow.
	"""
	if span is None or _TRACING_BACKEND != 'mlflow':
		return
	try:
		if inputs is not None:
			span.set_inputs(inputs)
			# browser-use messages are OpenAI-style {role, content}; hint MLflow's chat renderer
			span.set_attribute('mlflow.message.format', 'openai')
		if output is not None:
			span.set_outputs(output)
		if model is not None:
			span.set_attribute('mlflow.llm.model', model)
		if provider is not None:
			span.set_attribute('mlflow.llm.provider', provider)
		if usage is not None:
			token_usage: dict[str, Any] = {
				'input_tokens': getattr(usage, 'prompt_tokens', None),
				'output_tokens': getattr(usage, 'completion_tokens', None),
				'total_tokens': getattr(usage, 'total_tokens', None),
				# MLflow cache keys; always surface cache-read (0 when the model reports none) so it stays visible
				'cache_read_input_tokens': getattr(usage, 'prompt_cached_tokens', None) or 0,
			}
			creation = getattr(usage, 'prompt_cache_creation_tokens', None)
			if creation:
				token_usage['cache_creation_input_tokens'] = creation
			span.set_attribute('mlflow.chat.tokenUsage', token_usage)
		if cost is not None:
			span.set_attribute(
				'mlflow.llm.cost',
				{
					'input_cost': getattr(cost, 'prompt_cost', None),
					'output_cost': getattr(cost, 'completion_cost', None),
					'total_cost': getattr(cost, 'total_cost', None),
				},
			)
	except Exception:
		pass


def set_action_output(span: Any, result: Any) -> None:
	"""Record an action span's output on whichever backend is active. Best-effort; never raises."""
	if span is None:
		return
	try:
		if _TRACING_BACKEND == 'mlflow':
			span.set_outputs(result)
		elif _TRACING_BACKEND == 'lmnr':
			from lmnr import Laminar

			Laminar.set_span_output(result)
	except Exception:
		pass


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
	span_type: Literal['DEFAULT', 'LLM', 'TOOL'] = 'DEFAULT',
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
	kwargs = {
		'name': name,
		'ignore_input': ignore_input,
		'ignore_output': ignore_output,
		'metadata': metadata,
		'span_type': span_type,
		'tags': ['observe', 'observe_debug'],  # important: tags need to be created on laminar first
		**kwargs,
	}

	if _TRACING_BACKEND == 'lmnr' and _lmnr_observe:
		# Use the real lmnr observe decorator
		return cast(Callable[[F], F], _lmnr_observe(**kwargs))
	elif _TRACING_BACKEND == 'mlflow':
		# Route spans to MLflow
		return _create_mlflow_decorator(**kwargs)
	else:
		# Use no-op decorator
		return _create_no_op_decorator(**kwargs)


def observe_debug(
	name: str | None = None,
	ignore_input: bool = False,
	ignore_output: bool = False,
	metadata: dict[str, Any] | None = None,
	span_type: Literal['DEFAULT', 'LLM', 'TOOL'] = 'DEFAULT',
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
	kwargs = {
		'name': name,
		'ignore_input': ignore_input,
		'ignore_output': ignore_output,
		'metadata': metadata,
		'span_type': span_type,
		'tags': ['observe_debug'],  # important: tags need to be created on laminar first
		**kwargs,
	}

	if _is_debug_mode() and _TRACING_BACKEND == 'lmnr' and _lmnr_observe:
		# Use the real lmnr observe decorator only in debug mode
		return cast(Callable[[F], F], _lmnr_observe(**kwargs))
	elif _is_debug_mode() and _TRACING_BACKEND == 'mlflow':
		# Route spans to MLflow only in debug mode
		return _create_mlflow_decorator(**kwargs)
	else:
		# Use no-op decorator (either not in debug mode or no tracing backend available)
		return _create_no_op_decorator(**kwargs)


# Convenience functions for checking availability and debug status
def is_lmnr_available() -> bool:
	"""Check if lmnr is available for tracing."""
	return _LMNR_AVAILABLE


def is_mlflow_available() -> bool:
	"""Check if mlflow is available for tracing."""
	return _MLFLOW_AVAILABLE


def get_tracing_backend() -> str:
	"""Return the active tracing backend: 'lmnr', 'mlflow', or 'none'."""
	return _TRACING_BACKEND


def is_debug_mode() -> bool:
	"""Check if we're currently in debug mode."""
	return _is_debug_mode()


def get_observability_status() -> dict[str, bool]:
	"""Get the current status of observability features."""
	active = _TRACING_BACKEND != 'none'
	return {
		'lmnr_available': _LMNR_AVAILABLE,
		'mlflow_available': _MLFLOW_AVAILABLE,
		'debug_mode': _is_debug_mode(),
		'observe_active': active,
		'observe_debug_active': active and _is_debug_mode(),
	}
