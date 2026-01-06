"""Namespace initialization for code-use mode.

This module creates a namespace with all browser tools available as functions,
similar to a Jupyter notebook environment.
"""

import asyncio
import csv
import datetime
import json
import logging
import re
from pathlib import Path
from typing import Any

import requests

from browser_use.browser import BrowserSession
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel
from browser_use.tools.service import CodeAgentTools, Tools

logger = logging.getLogger(__name__)

# Try to import optional data science libraries
try:
	import numpy as np  # type: ignore

	NUMPY_AVAILABLE = True
except ImportError:
	NUMPY_AVAILABLE = False

try:
	import pandas as pd  # type: ignore

	PANDAS_AVAILABLE = True
except ImportError:
	PANDAS_AVAILABLE = False

try:
	import matplotlib.pyplot as plt  # type: ignore

	MATPLOTLIB_AVAILABLE = True
except ImportError:
	MATPLOTLIB_AVAILABLE = False

try:
	from bs4 import BeautifulSoup  # type: ignore

	BS4_AVAILABLE = True
except ImportError:
	BS4_AVAILABLE = False

try:
	from pypdf import PdfReader  # type: ignore

	PYPDF_AVAILABLE = True
except ImportError:
	PYPDF_AVAILABLE = False

try:
	from tabulate import tabulate  # type: ignore

	TABULATE_AVAILABLE = True
except ImportError:
	TABULATE_AVAILABLE = False


def _strip_js_comments(js_code: str) -> str:
	"""
	Remove JavaScript comments before CDP evaluation.
	CDP's Runtime.evaluate doesn't handle comments in all contexts.

	Args:
		js_code: JavaScript code potentially containing comments

	Returns:
		JavaScript code with comments stripped
	"""
	# Remove multi-line comments (/* ... */)
	js_code = re.sub(r'/\*.*?\*/', '', js_code, flags=re.DOTALL)

	# Remove single-line comments - only lines that START with // (after whitespace)
	# This avoids breaking XPath strings, URLs, regex patterns, etc.
	js_code = re.sub(r'^\s*//.*$', '', js_code, flags=re.MULTILINE)

	return js_code


class EvaluateError(Exception):
	"""Special exception raised by evaluate() to stop Python execution immediately."""

	pass


async def validate_task_completion(
	task: str,
	output: str | None,
	llm: BaseChatModel,
) -> tuple[bool, str]:
	"""
	Validate if task is truly complete by asking LLM without system prompt or history.

	Args:
		task: The original task description
		output: The output from the done() call
		llm: The LLM to use for validation

	Returns:
		Tuple of (is_complete, reasoning)
	"""
	from browser_use.llm.messages import UserMessage

	# Build validation prompt
	validation_prompt = f"""You are a task completion validator. Analyze if the agent has truly completed the user's task.

**Original Task:**
{task}

**Agent's Output:**
{output[:100000] if output else '(No output provided)'}

**Your Task:**
Determine if the agent has successfully completed the user's task. Consider:
1. Has the agent delivered what the user requested?
2. If data extraction was requested, is there actual data?
3. If the task is impossible (e.g., localhost website, login required but no credentials), is it truly impossible?
4. Could the agent continue and make meaningful progress?

**Response Format:**
Reasoning: [Your analysis of whether the task is complete]
Verdict: [YES or NO]

YES = Task is complete OR truly impossible to complete
NO = Agent should continue working"""

	try:
		# Call LLM with just the validation prompt (no system prompt, no history)
		response = await llm.ainvoke([UserMessage(content=validation_prompt)])
		response_text = response.completion

		# Parse the response
		reasoning = ''
		verdict = 'NO'

		# Extract reasoning and verdict
		lines = response_text.split('\n')
		for line in lines:
			if line.strip().lower().startswith('reasoning:'):
				reasoning = line.split(':', 1)[1].strip()
			elif line.strip().lower().startswith('verdict:'):
				verdict_text = line.split(':', 1)[1].strip().upper()
				if 'YES' in verdict_text:
					verdict = 'YES'
				elif 'NO' in verdict_text:
					verdict = 'NO'

		# If we couldn't parse, try to find YES/NO in the response
		if not reasoning:
			reasoning = response_text

		is_complete = verdict == 'YES'

		logger.info(f'Task validation: {verdict}')
		logger.debug(f'Validation reasoning: {reasoning}')

		return is_complete, reasoning

	except Exception as e:
		logger.warning(f'Failed to validate task completion: {e}')
		# On error, assume the agent knows what they're doing
		return True, f'Validation failed: {e}'


async def evaluate(code: str, browser_session: BrowserSession) -> Any:
	"""
	Execute JavaScript code in the browser and return the result.

	Args:
		code: JavaScript code to execute (must be wrapped in IIFE)

	Returns:
		The result of the JavaScript execution

	Raises:
		EvaluateError: If JavaScript execution fails. This stops Python execution immediately.

	Example:
		result = await evaluate('''
		(function(){
			return Array.from(document.querySelectorAll('.product')).map(p => ({
				name: p.querySelector('.name').textContent,
				price: p.querySelector('.price').textContent
			}))
		})()
		''')
	"""
	# Strip JavaScript comments before CDP evaluation (CDP doesn't support them in all contexts)
	code = _strip_js_comments(code)

	cdp_session = await browser_session.get_or_create_cdp_session()

	try:
		# Execute JavaScript with proper error handling
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': code, 'returnByValue': True, 'awaitPromise': True},
			session_id=cdp_session.session_id,
		)

		# Check for JavaScript execution errors
		if result.get('exceptionDetails'):
			exception = result['exceptionDetails']
			error_text = exception.get('text', 'Unknown error')

			# Try to get more details from the exception
			error_details = []
			if 'exception' in exception:
				exc_obj = exception['exception']
				if 'description' in exc_obj:
					error_details.append(exc_obj['description'])
				elif 'value' in exc_obj:
					error_details.append(str(exc_obj['value']))

			# Build comprehensive error message with full CDP context
			error_msg = f'JavaScript execution error: {error_text}'
			if error_details:
				error_msg += f'\nDetails: {" | ".join(error_details)}'

			# Raise special exception that will stop Python execution immediately
			raise EvaluateError(error_msg)

		# Get the result data
		result_data = result.get('result', {})

		# Get the actual value
		value = result_data.get('value')

		# Return the value directly
		if value is None:
			return None if 'value' in result_data else 'undefined'
		elif isinstance(value, (dict, list)):
			# Complex objects - already deserialized by returnByValue
			return value
		else:
			# Primitive values
			return value

	except EvaluateError:
		# Re-raise EvaluateError as-is to stop Python execution
		raise
	except Exception as e:
		# Wrap other exceptions in EvaluateError
		raise EvaluateError(f'Failed to execute JavaScript: {type(e).__name__}: {e}') from e


def create_namespace(
	browser_session: BrowserSession,
	tools: Tools | None = None,
	page_extraction_llm: BaseChatModel | None = None,
	file_system: FileSystem | None = None,
	available_file_paths: list[str] | None = None,
	sensitive_data: dict[str, str | dict[str, str]] | None = None,
) -> dict[str, Any]:
	"""
	Create a namespace with all browser tools available as functions.

	This function creates a dictionary of functions that can be used to interact
	with the browser, similar to a Jupyter notebook environment.

	Args:
		browser_session: The browser session to use
		tools: Optional Tools instance (will create default if not provided)
		page_extraction_llm: Optional LLM for page extraction
		file_system: Optional file system for file operations
		available_file_paths: Optional list of available file paths
		sensitive_data: Optional sensitive data dictionary

	Returns:
		Dictionary containing all available functions and objects

	Example:
		namespace = create_namespace(browser_session)
		await namespace['navigate'](url='https://google.com')
		result = await namespace['evaluate']('document.title')
	"""
	if tools is None:
		# Use CodeAgentTools with default exclusions optimized for code-use mode
		# For code-use, we keep: navigate, evaluate, wait, done
		# and exclude: most browser interaction, file system actions (use Python instead)
		tools = CodeAgentTools()

	if available_file_paths is None:
		available_file_paths = []

	namespace: dict[str, Any] = {
		# Core objects
		'browser': browser_session,
		'file_system': file_system,
		# Standard library modules (always available)
		'json': json,
		'asyncio': asyncio,
		'Path': Path,
		'csv': csv,
		're': re,
		'datetime': datetime,
		'requests': requests,
	}

	# Add optional data science libraries if available
	if NUMPY_AVAILABLE:
		namespace['np'] = np
		namespace['numpy'] = np
	if PANDAS_AVAILABLE:
		namespace['pd'] = pd
		namespace['pandas'] = pd
	if MATPLOTLIB_AVAILABLE:
		namespace['plt'] = plt
		namespace['matplotlib'] = plt
	if BS4_AVAILABLE:
		namespace['BeautifulSoup'] = BeautifulSoup
		namespace['bs4'] = BeautifulSoup
	if PYPDF_AVAILABLE:
		namespace['PdfReader'] = PdfReader
		namespace['pypdf'] = PdfReader
	if TABULATE_AVAILABLE:
		namespace['tabulate'] = tabulate

	# Track failed evaluate() calls to detect repeated failed approaches
	if '_evaluate_failures' not in namespace:
		namespace['_evaluate_failures'] = []

	# Add custom evaluate function that returns values directly
	async def evaluate_wrapper(
		code: str | None = None, variables: dict[str, Any] | None = None, *_args: Any, **kwargs: Any
	) -> Any:
		# Handle both positional and keyword argument styles
		if code is None:
			# Check if code was passed as keyword arg
			code = kwargs.get('code', kwargs.get('js_code', kwargs.get('expression', '')))
		# Extract variables if passed as kwarg
		if variables is None:
			variables = kwargs.get('variables')

		if not code:
			raise ValueError('No JavaScript code provided to evaluate()')

		# Inject variables if provided
		if variables:
			vars_json = json.dumps(variables)
			stripped = code.strip()

			# Check if code is already a function expression expecting params
			# Pattern: (function(params) { ... }) or (async function(params) { ... })
			if re.match(r'\((?:async\s+)?function\s*\(\s*\w+\s*\)', stripped):
				# Already expects params, wrap to call it with our variables
				code = f'(function(){{ const params = {vars_json}; return {stripped}(params); }})()'
			else:
				# Not a parameterized function, inject params in scope
				# Check if already wrapped in IIFE (including arrow function IIFEs)
				is_wrapped = (
					(stripped.startswith('(function()') and '})()' in stripped[-10:])
					or (stripped.startswith('(async function()') and '})()' in stripped[-10:])
					or (stripped.startswith('(() =>') and ')()' in stripped[-10:])
					or (stripped.startswith('(async () =>') and ')()' in stripped[-10:])
				)
				if is_wrapped:
					# Already wrapped, inject params at the start
					# Try to match regular function IIFE
					match = re.match(r'(\((?:async\s+)?function\s*\(\s*\)\s*\{)', stripped)
					if match:
						prefix = match.group(1)
						rest = stripped[len(prefix) :]
						code = f'{prefix} const params = {vars_json}; {rest}'
					else:
						# Try to match arrow function IIFE
						# Patterns: (() => expr)() or (() => { ... })() or (async () => ...)()
						arrow_match = re.match(r'(\((?:async\s+)?\(\s*\)\s*=>\s*\{)', stripped)
						if arrow_match:
							# Arrow function with block body: (() => { ... })()
							prefix = arrow_match.group(1)
							rest = stripped[len(prefix) :]
							code = f'{prefix} const params = {vars_json}; {rest}'
						else:
							# Arrow function with expression body or fallback: wrap in outer function
							code = f'(function(){{ const params = {vars_json}; return {stripped}; }})()'
				else:
					# Not wrapped, wrap with params
					code = f'(function(){{ const params = {vars_json}; {code} }})()'
					# Skip auto-wrap below
					return await evaluate(code, browser_session)

		# Auto-wrap in IIFE if not already wrapped (and no variables were injected)
		if not variables:
			stripped = code.strip()
			# Check for regular function IIFEs, async function IIFEs, and arrow function IIFEs
			is_wrapped = (
				(stripped.startswith('(function()') and '})()' in stripped[-10:])
				or (stripped.startswith('(async function()') and '})()' in stripped[-10:])
				or (stripped.startswith('(() =>') and ')()' in stripped[-10:])
				or (stripped.startswith('(async () =>') and ')()' in stripped[-10:])
			)
			if not is_wrapped:
				code = f'(function(){{{code}}})()'

		# Execute and track failures
		try:
			result = await evaluate(code, browser_session)

			# Print result structure for debugging
			if isinstance(result, list) and result and isinstance(result[0], dict):
				result_preview = f'list of dicts - len={len(result)}, example 1:\n'
				sample_result = result[0]
				for key, value in list(sample_result.items())[:10]:
					value_str = str(value)[:10] if not isinstance(value, (int, float, bool, type(None))) else str(value)
					result_preview += f'  {key}: {value_str}...\n'
				if len(sample_result) > 10:
					result_preview += f'  ... {len(sample_result) - 10} more keys'
				print(result_preview)

			elif isinstance(result, list):
				if len(result) == 0:
					print('type=list, len=0')
				else:
					result_preview = str(result)[:100]
					print(f'type=list, len={len(result)}, preview={result_preview}...')
			elif isinstance(result, dict):
				result_preview = f'type=dict, len={len(result)}, sample keys:\n'
				for key, value in list(result.items())[:10]:
					value_str = str(value)[:10] if not isinstance(value, (int, float, bool, type(None))) else str(value)
					result_preview += f'  {key}: {value_str}...\n'
				if len(result) > 10:
					result_preview += f'  ... {len(result) - 10} more keys'
				print(result_preview)

			else:
				print(f'type={type(result).__name__}, value={repr(result)[:50]}')

			return result
		except Exception as e:
			# Track errors for pattern detection
			namespace['_evaluate_failures'].append({'error': str(e), 'type': 'exception'})
			raise

	namespace['evaluate'] = evaluate_wrapper

	# Add get_selector_from_index helper for code_use mode
	async def get_selector_from_index_wrapper(index: int) -> str:
		"""
		Get the CSS selector for an element by its interactive index.

		This allows you to use the element's index from the browser state to get
		its CSS selector for use in JavaScript evaluate() calls.

		Args:
			index: The interactive index from the browser state (e.g., [123])

		Returns:
			str: CSS selector that can be used in JavaScript

		Example:
			selector = await get_selector_from_index(123)
			await evaluate(f'''
			(function(){{
				const el = document.querySelector({json.dumps(selector)});
				if (el) el.click();
			}})()
			''')
		"""
		from browser_use.dom.utils import generate_css_selector_for_element

		# Get element by index from browser session
		node = await browser_session.get_element_by_index(index)
		if node is None:
			msg = f'Element index {index} not available - page may have changed. Try refreshing browser state.'
			logger.warning(f'⚠️ {msg}')
			raise RuntimeError(msg)

		# Check if element is in shadow DOM
		shadow_hosts = []
		current = node.parent_node
		while current:
			if current.shadow_root_type is not None:
				# This is a shadow host
				host_tag = current.tag_name.lower()
				host_id = current.attributes.get('id', '') if current.attributes else ''
				host_desc = f'{host_tag}#{host_id}' if host_id else host_tag
				shadow_hosts.insert(0, host_desc)
			current = current.parent_node

		# Check if in iframe
		in_iframe = False
		current = node.parent_node
		while current:
			if current.tag_name.lower() == 'iframe':
				in_iframe = True
				break
			current = current.parent_node

		# Use the robust selector generation function (now handles special chars in IDs)
		selector = generate_css_selector_for_element(node)

		# Log shadow DOM/iframe info if detected
		if shadow_hosts:
			shadow_path = ' > '.join(shadow_hosts)
			logger.info(f'Element [{index}] is inside Shadow DOM. Path: {shadow_path}')
			logger.info(f'    Selector: {selector}')
			logger.info(
				f'    To access: document.querySelector("{shadow_hosts[0].split("#")[0]}").shadowRoot.querySelector("{selector}")'
			)
		if in_iframe:
			logger.info(f"Element [{index}] is inside an iframe. Regular querySelector won't work.")

		if selector:
			return selector

		# Fallback: just use tag name if available
		if node.tag_name:
			return node.tag_name.lower()

		raise ValueError(f'Could not generate selector for element index {index}')

	namespace['get_selector_from_index'] = get_selector_from_index_wrapper

	# Inject all tools as functions into the namespace
	# Skip 'evaluate' since we have a custom implementation above
	for action_name, action in tools.registry.registry.actions.items():
		if action_name == 'evaluate':
			continue  # Skip - use custom evaluate that returns Python objects directly
		param_model = action.param_model
		action_function = action.function

		# Create a closure to capture the current action_name, param_model, and action_function
		def make_action_wrapper(act_name, par_model, act_func):
			async def action_wrapper(*args, **kwargs):
				# Convert positional args to kwargs based on param model fields
				if args:
					# Get the field names from the pydantic model
					field_names = list(par_model.model_fields.keys())
					for i, arg in enumerate(args):
						if i < len(field_names):
							kwargs[field_names[i]] = arg

				# Create params from kwargs
				try:
					params = par_model(**kwargs)
				except Exception as e:
					raise ValueError(f'Invalid parameters for {act_name}: {e}') from e

				# Special validation for done() - enforce minimal code cell
				if act_name == 'done':
					consecutive_failures = namespace.get('_consecutive_errors')
					if consecutive_failures and consecutive_failures > 3:
						pass

					else:
						# Check if there are multiple Python blocks in this response
						all_blocks = namespace.get('_all_code_blocks', {})
						python_blocks = [k for k in sorted(all_blocks.keys()) if k.startswith('python_')]

						if len(python_blocks) > 1:
							msg = (
								'done() should be the ONLY code block in the response.\n'
								'You have multiple Python blocks in this response. Consider calling done() in a separate response '
								'Now verify the last output and if it satisfies the task, call done(), else continue working.'
							)
							print(msg)

						# Get the current cell code from namespace (injected by service.py before execution)
						current_code = namespace.get('_current_cell_code')
						if current_code and isinstance(current_code, str):
							# Count non-empty, non-comment lines
							lines = [line.strip() for line in current_code.strip().split('\n')]
							code_lines = [line for line in lines if line and not line.startswith('#')]

							# Check if the line above await done() contains an if block
							done_line_index = -1
							for i, line in enumerate(reversed(code_lines)):
								if 'await done()' in line or 'await done(' in line:
									done_line_index = len(code_lines) - 1 - i
									break

							has_if_above = False
							has_else_above = False
							has_elif_above = False
							if done_line_index > 0:
								line_above = code_lines[done_line_index - 1]
								has_if_above = line_above.strip().startswith('if ') and line_above.strip().endswith(':')
								has_else_above = line_above.strip().startswith('else:')
								has_elif_above = line_above.strip().startswith('elif ')
							if has_if_above or has_else_above or has_elif_above:
								msg = (
									'done() should be called individually after verifying the result from any logic.\n'
									'Consider validating your output first, THEN call done() in a final step without if/else/elif blocks only if the task is truly complete.'
								)
								logger.error(msg)
								print(msg)
								raise RuntimeError(msg)

				# Build special context
				special_context = {
					'browser_session': browser_session,
					'page_extraction_llm': page_extraction_llm,
					'available_file_paths': available_file_paths,
					'has_sensitive_data': False,  # Can be handled separately if needed
					'file_system': file_system,
				}

				# Execute the action
				result = await act_func(params=params, **special_context)

				# For code-use mode, we want to return the result directly
				# not wrapped in ActionResult
				if hasattr(result, 'extracted_content'):
					# Special handling for done action - mark task as complete
					if act_name == 'done' and hasattr(result, 'is_done') and result.is_done:
						namespace['_task_done'] = True
						# Store the extracted content as the final result
						if result.extracted_content:
							namespace['_task_result'] = result.extracted_content
						# Store the self-reported success status
						if hasattr(result, 'success'):
							namespace['_task_success'] = result.success

					# If there's extracted content, return it
					if result.extracted_content:
						return result.extracted_content
					# If there's an error, raise it
					if result.error:
						raise RuntimeError(result.error)
					# Otherwise return None
					return None
				return result

			return action_wrapper

		# Rename 'input' to 'input_text' to avoid shadowing Python's built-in input()
		namespace_action_name = 'input_text' if action_name == 'input' else action_name

		# Add the wrapper to the namespace
		namespace[namespace_action_name] = make_action_wrapper(action_name, param_model, action_function)

	return namespace


def get_namespace_documentation(namespace: dict[str, Any]) -> str:
	"""
	Generate documentation for all available functions in the namespace.

	Args:
		namespace: The namespace dictionary

	Returns:
		Markdown-formatted documentation string
	"""
	docs = ['# Available Functions\n']

	# Document each function
	for name, obj in sorted(namespace.items()):
		if callable(obj) and not name.startswith('_'):
			# Get function signature and docstring
			if hasattr(obj, '__doc__') and obj.__doc__:
				docs.append(f'## {name}\n')
				docs.append(f'{obj.__doc__}\n')

	return '\n'.join(docs)
