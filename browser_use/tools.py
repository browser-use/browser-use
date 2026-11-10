"""Custom actions: plain functions the model can call as tools, next to its Python REPL.

tools = Tools()

@tools.action('Look up the internal price of a product')
def get_price(sku: str) -> str:
    return prices[sku]

Agent(task, tools=tools)
"""

from __future__ import annotations

import ast
import inspect
import logging
import re
import textwrap
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic_ai import Tool

from browser_use.exceptions import removed

logger = logging.getLogger(__name__)
# 0.x's browser_use.tools was a package (tools.service, tools.registry.views, ...): an empty __path__ lets those imports
# reach the 0.x import hook (browser_use/legacy.py), which names Tools; without it Python stops at "not a package"
__path__: list[str] = []
RESERVED = {'python', 'finish', 'finish_from_repl'}
# Retries of one tool's rejected calls (invalid or truncated arguments, ModelRetry). bu-pi returns the error and goes on;
# max_steps bounds it. A budget of 1 ended the run on two bad python calls in a row (a truncated cell, a JSON slip).
TOOL_RETRIES = 1_000_000
TOOL_NAME = re.compile(r'[a-zA-Z0-9_-]{1,64}')  # what OpenAI, Anthropic and Google accept
# 0.13.14 injected these into actions (registry _get_special_param_types); any other name, `page` or `browser` too,
# came from the model and still does. 1.0 actions get only what the model passes; the model drives the browser in Python.
INJECTED = {
	'browser_session',
	'context',
	'cdp_client',
	'page_url',
	'page_extraction_llm',
	'file_system',
	'available_file_paths',
	'has_sensitive_data',
	'extraction_schema',
}


class RemovedField(TypeError):
	"""A 0.x ActionResult field 1.0 dropped. It ends the run (never handed to the model as a tool error), so the
	developer sees it."""


REMOVED_FIELDS = {  # 0.x ActionResult fields -> the 1.0 alternative
	'is_done': 'the model ends the run with finish.',
	# kept as an extra field it reached the model as JSON text: base64 image data in the conversation, never an image
	'images': 'return text; the agent takes screenshots itself (screenshot()).',
	'success': 'the model may give a verdict in finish(..., success=...); result.success holds it (None when omitted).',
	'attachments': 'save files in the workspace; files the agent wrote there are delivered.',
}
# Ignored with a warning, never raised: an action runs after the browser started (and a cloud browser is billed), and
# 1.0 keeps every result in the conversation anyway
IGNORED_FIELDS: dict[str, str] = dict.fromkeys(
	('include_in_memory', 'include_extracted_content_only_once'), 'every action result stays in the conversation.'
)
_warned: set[str] = set()


class ActionResult(BaseModel):
	"""0.x return type, kept so existing actions run. The model sees it as JSON."""

	model_config = ConfigDict(extra='allow')

	extracted_content: str | None = None
	error: str | None = None

	@model_validator(mode='before')
	@classmethod
	def _no_removed_fields(cls, data: Any) -> Any:
		if isinstance(data, dict):
			data = _without_0x_defaults(data)
		if isinstance(data, dict) and (name := next((k for k in data if k in REMOVED_FIELDS), None)):
			raise RemovedField(removed(f'ActionResult({name}=...)', REMOVED_FIELDS[name]))
		if isinstance(data, dict) and (name := next((k for k in data if k in IGNORED_FIELDS), None)):
			if name not in _warned:  # once: an action returns it on every call
				_warned.add(name)
				logger.warning(f'ActionResult({name}=...) is ignored in browser-use 1.0: {IGNORED_FIELDS[name]}')
			data = {k: v for k, v in data.items() if k != name}
		return data


def _without_0x_defaults(data: dict) -> dict:
	"""0.x actions often spelled out the defaults: ActionResult(extracted_content=..., is_done=False, success=True). Those
	changed nothing in 0.x (success counted only with is_done=True), so they ended a billed run for no reason."""
	if data.get('is_done'):
		return data
	return {k: v for k, v in data.items() if not (k in REMOVED_FIELDS and (k in ('is_done', 'success') or not v))}


def _check_done_results(fn: Callable) -> None:
	"""An action whose source returns ActionResult(is_done=True, ...) (the 0.x way to end the run) can only fail when
	it runs, after the browser started: refuse it when it is registered instead (any is_done but a literal False or
	None). An action without readable source still raises when it returns one."""
	try:
		tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
	except (OSError, TypeError, SyntaxError):  # no source (REPL, compiled), or a lambda's partial line
		return
	for node in ast.walk(tree):
		if isinstance(node, ast.Call) and getattr(node.func, 'id', getattr(node.func, 'attr', None)) == 'ActionResult':
			for kw in node.keywords:
				if kw.arg is None:  # ActionResult(**fields)
					continue
				done = kw.arg == 'is_done' and not _empty_literal(kw.value)
				# an empty list is the 0.x default spelled out: ActionResult drops it at runtime, so it runs
				listed = kw.arg in ('attachments', 'images') and not _empty_literal(kw.value)
				if done or listed:
					raise TypeError(
						removed(f'ActionResult({kw.arg}=...) in @tools.action {fn.__name__}()', REMOVED_FIELDS[kw.arg])
					)


def _empty_literal(node: ast.expr) -> bool:
	"""None, False, 0, '' or an empty list/tuple/set/dict written as a literal: a value ActionResult drops as a default."""
	if isinstance(node, ast.Constant):
		return not node.value
	if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
		return not node.elts
	return isinstance(node, ast.Dict) and not node.keys


TOOLS_REMOVED = {  # 0.x Tools(...) / Controller(...) arguments -> the 1.0 alternative
	'exclude_actions': 'there are no built-in actions to exclude: the model acts in Python.',
	'output_model': 'Agent(output_model_schema=...).',
	'display_files_in_done_text': '',
	# 0.1.x Controller took browser options
	**dict.fromkeys(
		('headless', 'keep_open', 'disable_security', 'cookies_path', 'browser_config'), 'pass options to Browser(...).'
	),
}
TOOLS_METHODS_REMOVED = {  # 0.x Tools / Controller methods -> the 1.0 alternative
	'act': 'the model calls the actions; there are no built-in ones to run.',
	'exclude_action': 'there are no built-in actions to exclude: the model acts in Python.',
	**dict.fromkeys(('get_output_model', 'use_structured_output_action'), 'Agent(output_model_schema=...).'),
	'set_coordinate_clicking': 'the agent clicks with Python (click_at_xy, raw CDP).',
}
ACTION_REMOVED = {  # 0.x @registry.action(...) arguments -> the 1.0 alternative
	'page_filter': 'Browser(allowed_domains=...) limits where the whole browser navigates.',
	'requires_browser': 'actions get only the arguments the model passes; the model drives the browser itself in Python.',
	'terminates_sequence': 'each step is one Python cell, so there is no action sequence to end: delete it.',
}


class Tools:
	def __init__(self, **kwargs: Any) -> None:
		if kwargs:
			name = next(iter(kwargs))
			if name not in TOOLS_REMOVED:
				raise TypeError(f'Tools({name}=...) is not a browser-use 1.0 option; see MIGRATING.md.')
			raise TypeError(removed(f'Tools({name}=...)', TOOLS_REMOVED[name]))
		self.functions: list[Tool] = []

	@property
	def registry(self) -> Tools:  # 0.x: @controller.registry.action(...)
		return self

	def __getattr__(self, name: str) -> Any:
		if name in TOOLS_METHODS_REMOVED:
			raise AttributeError(removed(f'Tools.{name}()', TOOLS_METHODS_REMOVED[name]))
		raise AttributeError(f'{type(self).__name__!r} object has no attribute {name!r}')

	def action(
		self,
		description: str = '',
		param_model: type[BaseModel] | None = None,
		domains: list[str] | None = None,
		allowed_domains: list[str] | None = None,
		**kwargs: Any,
	) -> Callable[[Callable], Callable]:
		if callable(description):  # @tools.action without parentheses registered nothing
			raise TypeError("Use @tools.action('what the action does') with parentheses; @tools.action alone registers nothing")
		if domains or allowed_domains:
			name = 'domains' if domains else 'allowed_domains'
			raise TypeError(
				removed(f'@tools.action({name}=...)', 'Browser(allowed_domains=...) limits where the whole browser navigates.')
			)
		if kwargs:
			name = next(iter(kwargs))
			if name in ACTION_REMOVED:
				raise TypeError(removed(f'@tools.action({name}=...)', ACTION_REMOVED[name]))
			raise TypeError(f'@tools.action({name}=...) is not a browser-use 1.0 option; see MIGRATING.md.')

		def decorator(fn: Callable) -> Callable:
			params = list(inspect.signature(fn).parameters)
			injected = [p for p in params if p in INJECTED]
			if injected:
				raise TypeError(
					removed(
						f'Injecting {", ".join(injected)} into @tools.action {fn.__name__}()',
						'actions get only the arguments the model passes; the model drives the browser itself in Python.',
					)
				)
			if fn.__name__ in RESERVED:
				raise ValueError(f'@tools.action: {fn.__name__!r} is a built-in tool name; rename the function')
			if not TOOL_NAME.fullmatch(fn.__name__):  # a lambda ('<lambda>') failed only at the provider, with a 400
				raise ValueError(
					f'@tools.action: {fn.__name__!r} is not a valid tool name (letters, digits, _ and -, at most 64); use a '
					'named function'
				)
			_check_done_results(fn)
			if param_model is not None and params:  # 0.x: def action(params, ...) with param_model=Model; it wins
				fn.__annotations__[params[0]] = param_model
			# 0.x kept actions by name: registering one again (a notebook cell run twice) replaces it
			self.functions = [t for t in self.functions if t.name != fn.__name__]
			self.functions.append(
				Tool(fn, takes_ctx=False, name=fn.__name__, description=description or None, max_retries=TOOL_RETRIES)
			)
			return fn

		return decorator


Controller = Tools  # 0.x alias


if not TYPE_CHECKING:  # pyright would accept any name imported from here
	from browser_use.legacy import removed_names

	__getattr__ = removed_names(__name__)  # from browser_use.tools import registry (0.x): the removed error naming Tools
