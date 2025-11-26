import ast
import asyncio
import base64
import dataclasses
import enum
import inspect
import json
import os
import sys
import textwrap
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import TYPE_CHECKING, Any, Concatenate, ParamSpec, TypeVar, Union, cast, get_args, get_origin

import cloudpickle
import httpx

from browser_use.sandbox.views import (
	BrowserCreatedData,
	ErrorData,
	LogData,
	ResultData,
	SandboxError,
	SSEEvent,
	SSEEventType,
)

if TYPE_CHECKING:
	from browser_use.browser import BrowserSession

T = TypeVar('T')
P = ParamSpec('P')


def get_terminal_width() -> int:
	"""Get terminal width, default to 80 if unable to detect"""
	try:
		return os.get_terminal_size().columns
	except (AttributeError, OSError):
		return 80


async def _call_callback(callback: Callable[..., Any], *args: Any) -> None:
	"""Call a callback that can be either sync or async"""
	result = callback(*args)
	if asyncio.iscoroutine(result):
		await result


def _get_function_source_without_decorator(func: Callable) -> str:
	"""Get function source code with decorator removed"""
	source = inspect.getsource(func)
	source = textwrap.dedent(source)

	# Parse and remove decorator
	tree = ast.parse(source)
	for node in ast.walk(tree):
		if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
			node.decorator_list = []
			break

	return ast.unparse(tree)


def _get_imports_used_in_function(func: Callable) -> str:
	"""Extract only imports that are referenced in the function body or type annotations"""
	# Get all names referenced in the function
	code = func.__code__
	referenced_names = set(code.co_names)

	# Also get names from type annotations (recursively for complex types like Union, Literal, etc.)
	def extract_type_names(annotation):
		"""Recursively extract all type names from annotation"""
		if annotation is None or annotation == inspect.Parameter.empty:
			return

		# Handle simple types with __name__
		if hasattr(annotation, '__name__'):
			referenced_names.add(annotation.__name__)

		# Handle string annotations
		if isinstance(annotation, str):
			referenced_names.add(annotation)

		# Handle generic types like Union[X, Y], Literal['x'], etc.
		origin = get_origin(annotation)
		args = get_args(annotation)

		if origin:
			# Add the origin type name (e.g., 'Union', 'Literal')
			if hasattr(origin, '__name__'):
				referenced_names.add(origin.__name__)

		# Recursively extract from generic args
		if args:
			for arg in args:
				extract_type_names(arg)

	sig = inspect.signature(func)
	for param in sig.parameters.values():
		if param.annotation != inspect.Parameter.empty:
			extract_type_names(param.annotation)

	# Get return annotation (also extract recursively)
	if 'return' in func.__annotations__:
		extract_type_names(func.__annotations__['return'])

	# Get the module where function is defined
	module = inspect.getmodule(func)
	if not module or not hasattr(module, '__file__') or module.__file__ is None:
		return ''

	try:
		with open(module.__file__) as f:
			module_source = f.read()

		tree = ast.parse(module_source)
		needed_imports: list[str] = []

		for node in tree.body:
			if isinstance(node, ast.Import):
				# import X, Y
				for alias in node.names:
					import_name = alias.asname if alias.asname else alias.name
					if import_name in referenced_names:
						needed_imports.append(ast.unparse(node))
						break
			elif isinstance(node, ast.ImportFrom):
				# from X import Y, Z
				imported_names = []
				for alias in node.names:
					import_name = alias.asname if alias.asname else alias.name
					if import_name in referenced_names:
						imported_names.append(alias)

				if imported_names:
					# Create filtered import statement
					filtered_import = ast.ImportFrom(module=node.module, names=imported_names, level=node.level)
					needed_imports.append(ast.unparse(filtered_import))

		return '\n'.join(needed_imports)
	except Exception:
		return ''


def _extract_all_params(func: Callable, args: tuple, kwargs: dict) -> dict[str, Any]:
	"""Extract all parameters including explicit params and closure variables

	Args:
		func: The function being decorated
		args: Positional arguments passed to the function
		kwargs: Keyword arguments passed to the function

	Returns:
		Dictionary of all parameters {name: value}
	"""
	sig = inspect.signature(func)
	bound_args = sig.bind_partial(*args, **kwargs)
	bound_args.apply_defaults()

	all_params: dict[str, Any] = {}

	# 1. Extract explicit parameters (skip 'browser' and 'self')
	for param_name, param_value in bound_args.arguments.items():
		if param_name == 'browser':
			continue
		if param_name == 'self' and hasattr(param_value, '__dict__'):
			# Extract self attributes as individual variables
			for attr_name, attr_value in param_value.__dict__.items():
				all_params[attr_name] = attr_value
		else:
			all_params[param_name] = param_value

	# 2. Extract closure variables
	if func.__closure__:
		closure_vars = func.__code__.co_freevars
		closure_values = [cell.cell_contents for cell in func.__closure__]

		for name, value in zip(closure_vars, closure_values):
			# Skip if already captured from explicit params
			if name in all_params:
				continue
			# Special handling for 'self' in closures
			if name == 'self' and hasattr(value, '__dict__'):
				for attr_name, attr_value in value.__dict__.items():
					if attr_name not in all_params:
						all_params[attr_name] = attr_value
			else:
				all_params[name] = value

	# 3. Extract referenced globals (like logger, module-level vars, etc.)
	#    Let cloudpickle handle serialization instead of special-casing
	for name in func.__code__.co_names:
		if name in all_params:
			continue
		if name in func.__globals__:
			all_params[name] = func.__globals__[name]

	return all_params


def sandbox(
	BROWSER_USE_API_KEY: str | None = None,
	cloud_profile_id: str | None = None,
	cloud_proxy_country_code: str | None = None,
	cloud_timeout: int | None = None,
	server_url: str | None = None,
	log_level: str = 'INFO',
	quiet: bool = False,
	headers: dict[str, str] | None = None,
	on_browser_created: Callable[[BrowserCreatedData], None]
	| Callable[[BrowserCreatedData], Coroutine[Any, Any, None]]
	| None = None,
	on_instance_ready: Callable[[], None] | Callable[[], Coroutine[Any, Any, None]] | None = None,
	on_log: Callable[[LogData], None] | Callable[[LogData], Coroutine[Any, Any, None]] | None = None,
	on_result: Callable[[ResultData], None] | Callable[[ResultData], Coroutine[Any, Any, None]] | None = None,
	on_error: Callable[[ErrorData], None] | Callable[[ErrorData], Coroutine[Any, Any, None]] | None = None,
	**env_vars: str,
) -> Callable[[Callable[Concatenate['BrowserSession', P], Coroutine[Any, Any, T]]], Callable[P, Coroutine[Any, Any, T]]]:
	"""Decorator to execute browser automation code in a sandbox environment.

	The decorated function MUST have 'browser: Browser' as its first parameter.
	The browser parameter will be automatically injected - do NOT pass it when calling the decorated function.
	All other parameters (explicit or from closure) will be captured and sent via cloudpickle.

	Args:
	    BROWSER_USE_API_KEY: API key (defaults to BROWSER_USE_API_KEY env var)
	    cloud_profile_id: The ID of the profile to use for the browser session
	    cloud_proxy_country_code: Country code for proxy location (e.g., 'us', 'uk', 'fr')
	    cloud_timeout: The timeout for the browser session in minutes (max 240 = 4 hours)
	    server_url: Sandbox server URL (defaults to https://sandbox.api.browser-use.com/sandbox-stream)
	    log_level: Logging level (INFO, DEBUG, WARNING, ERROR)
	    quiet: Suppress console output
	    headers: Additional HTTP headers to send with the request
	    on_browser_created: Callback when browser is created
	    on_instance_ready: Callback when instance is ready
	    on_log: Callback for log events
	    on_result: Callback when execution completes
	    on_error: Callback for errors
	    **env_vars: Additional environment variables

	Example:
	    @sandbox()
	    async def task(browser: Browser, url: str, max_steps: int) -> str:
	        agent = Agent(task=url, browser=browser)
	        await agent.run(max_steps=max_steps)
	        return "done"

	    # Call with:
	    result = await task(url="https://example.com", max_steps=10)

	    # With cloud parameters:
	    @sandbox(cloud_proxy_country_code='us', cloud_timeout=60)
	    async def task_with_proxy(browser: Browser) -> str:
	        ...
	"""

	def decorator(
		func: Callable[Concatenate['BrowserSession', P], Coroutine[Any, Any, T]],
	) -> Callable[P, Coroutine[Any, Any, T]]:
		# Validate function has browser parameter
		sig = inspect.signature(func)
		if 'browser' not in sig.parameters:
			raise TypeError(f'{func.__name__}() must have a "browser" parameter')

		browser_param = sig.parameters['browser']
		if browser_param.annotation != inspect.Parameter.empty:
			annotation_str = str(browser_param.annotation)
			if 'Browser' not in annotation_str:
				raise TypeError(f'{func.__name__}() browser parameter must be typed as Browser, got {annotation_str}')

		@wraps(func)
		async def wrapper(*args, **kwargs) -> T:
			# 1. Get API key
			api_key = BROWSER_USE_API_KEY or os.getenv('BROWSER_USE_API_KEY')
			if not api_key:
				raise SandboxError('BROWSER_USE_API_KEY is required')

			# 2. Extract all parameters (explicit + closure)
			all_params = _extract_all_params(func, args, kwargs)

			# 3. Get function source without decorator and only needed imports
			func_source = _get_function_source_without_decorator(func)
			needed_imports = _get_imports_used_in_function(func)

			# Always include Browser import since it's required for the function signature
			if needed_imports:
				needed_imports = 'from browser_use import Browser\n' + needed_imports
			else:
				needed_imports = 'from browser_use import Browser'

			# 4. Pickle parameters using cloudpickle for robust serialization
			pickled_params = base64.b64encode(cloudpickle.dumps(all_params)).decode()

			# 5. Determine which params are in the function signature vs closure/globals
			func_param_names = {p.name for p in sig.parameters.values() if p.name != 'browser'}
			non_explicit_params = {k: v for k, v in all_params.items() if k not in func_param_names}
			explicit_params = {k: v for k, v in all_params.items() if k in func_param_names}

			# Inject closure variables and globals as module-level vars
			var_injections = []
			for var_name in non_explicit_params.keys():
				var_injections.append(f"{var_name} = _params['{var_name}']")

			var_injection_code = '\n'.join(var_injections) if var_injections else '# No closure variables or globals'

			# Build function call
			if explicit_params:
				function_call = (
					f'await {func.__name__}(browser=browser, **{{k: _params[k] for k in {list(explicit_params.keys())!r}}})'
				)
			else:
				function_call = f'await {func.__name__}(browser=browser)'

			# 6. Create wrapper code that unpickles params and calls function
			execution_code = f"""import cloudpickle
import base64

# Imports used in function
{needed_imports}

# Unpickle all parameters (explicit, closure, and globals)
_pickled_params = base64.b64decode({repr(pickled_params)})
_params = cloudpickle.loads(_pickled_params)

# Inject closure variables and globals into module scope
{var_injection_code}

# Original function (decorator removed)
{func_source}

# Wrapper function that passes explicit params
async def run(browser):
	return {function_call}

"""

			# 9. Send to server
			payload: dict[str, Any] = {'code': base64.b64encode(execution_code.encode()).decode()}

			combined_env: dict[str, str] = env_vars.copy() if env_vars else {}
			combined_env['LOG_LEVEL'] = log_level.upper()
			payload['env'] = combined_env

			# Add cloud parameters if provided
			if cloud_profile_id is not None:
				payload['cloud_profile_id'] = cloud_profile_id
			if cloud_proxy_country_code is not None:
				payload['cloud_proxy_country_code'] = cloud_proxy_country_code
			if cloud_timeout is not None:
				payload['cloud_timeout'] = cloud_timeout

			url = server_url or 'https://sandbox.api.browser-use.com/sandbox-stream'

			request_headers = {'X-API-Key': api_key}
			if headers:
				request_headers.update(headers)

			# 10. Handle SSE streaming
			_NO_RESULT = object()
			execution_result = _NO_RESULT
			live_url_shown = False
			execution_started = False
			received_final_event = False

			async with httpx.AsyncClient(timeout=1800.0) as client:
				async with client.stream('POST', url, json=payload, headers=request_headers) as response:
					response.raise_for_status()

					try:
						async for line in response.aiter_lines():
							if not line or not line.startswith('data: '):
								continue

							event_json = line[6:]
							try:
								event = SSEEvent.from_json(event_json)

								if event.type == SSEEventType.BROWSER_CREATED:
									assert isinstance(event.data, BrowserCreatedData)

									if on_browser_created:
										try:
											await _call_callback(on_browser_created, event.data)
										except Exception as e:
											if not quiet:
												print(f'⚠️  Error in on_browser_created callback: {e}')

									if not quiet and event.data.live_url and not live_url_shown:
										width = get_terminal_width()
										print('\n' + '━' * width)
										print('👁️  LIVE BROWSER VIEW (Click to watch)')
										print(f'🔗 {event.data.live_url}')
										print('━' * width)
										live_url_shown = True

								elif event.type == SSEEventType.LOG:
									assert isinstance(event.data, LogData)
									message = event.data.message
									level = event.data.level

									if on_log:
										try:
											await _call_callback(on_log, event.data)
										except Exception as e:
											if not quiet:
												print(f'⚠️  Error in on_log callback: {e}')

									if level == 'stdout':
										if not quiet:
											if not execution_started:
												width = get_terminal_width()
												print('\n' + '─' * width)
												print('⚡ Runtime Output')
												print('─' * width)
												execution_started = True
											print(f'  {message}', end='')
									elif level == 'stderr':
										if not quiet:
											if not execution_started:
												width = get_terminal_width()
												print('\n' + '─' * width)
												print('⚡ Runtime Output')
												print('─' * width)
												execution_started = True
											print(f'⚠️  {message}', end='', file=sys.stderr)
									elif level == 'info':
										if not quiet:
											if 'credit' in message.lower():
												import re

												match = re.search(r'\$[\d,]+\.?\d*', message)
												if match:
													print(f'💰 You have {match.group()} credits')
											else:
												print(f'ℹ️  {message}')
									else:
										if not quiet:
											print(f'  {message}')

								elif event.type == SSEEventType.INSTANCE_READY:
									if on_instance_ready:
										try:
											await _call_callback(on_instance_ready)
										except Exception as e:
											if not quiet:
												print(f'⚠️  Error in on_instance_ready callback: {e}')

									if not quiet:
										print('✅ Browser ready, starting execution...\n')

								elif event.type == SSEEventType.RESULT:
									assert isinstance(event.data, ResultData)
									exec_response = event.data.execution_response
									received_final_event = True

									if on_result:
										try:
											await _call_callback(on_result, event.data)
										except Exception as e:
											if not quiet:
												print(f'⚠️  Error in on_result callback: {e}')

									if exec_response.success:
										execution_result = exec_response.result
										if not quiet and execution_started:
											width = get_terminal_width()
											print('\n' + '─' * width)
											print()
									else:
										error_msg = exec_response.error or 'Unknown error'
										raise SandboxError(f'Execution failed: {error_msg}')

								elif event.type == SSEEventType.ERROR:
									assert isinstance(event.data, ErrorData)
									received_final_event = True

									if on_error:
										try:
											await _call_callback(on_error, event.data)
										except Exception as e:
											if not quiet:
												print(f'⚠️  Error in on_error callback: {e}')

									raise SandboxError(f'Execution failed: {event.data.error}')

							except (json.JSONDecodeError, ValueError):
								continue

					except (httpx.RemoteProtocolError, httpx.ReadError, httpx.StreamClosed) as e:
						# With deterministic handshake, these should never happen
						# If they do, it's a real error
						raise SandboxError(
							f'Stream error: {e.__class__.__name__}: {e or "connection closed unexpectedly"}'
						) from e

			# 11. Parse result with type annotation
			if execution_result is not _NO_RESULT:
				return_annotation = func.__annotations__.get('return')
				if return_annotation:
					parsed_result = _parse_with_type_annotation(execution_result, return_annotation)
					return parsed_result
				return execution_result  # type: ignore[return-value]

			raise SandboxError('No result received from execution')

		# Update wrapper signature to remove browser parameter
		wrapper.__annotations__ = func.__annotations__.copy()
		if 'browser' in wrapper.__annotations__:
			del wrapper.__annotations__['browser']

		params = [p for p in sig.parameters.values() if p.name != 'browser']
		wrapper.__signature__ = sig.replace(parameters=params)  # type: ignore[attr-defined]

		return cast(Callable[P, Coroutine[Any, Any, T]], wrapper)

	return decorator


def _parse_with_type_annotation(data: Any, annotation: Any) -> Any:
	"""Parse data with type annotation without validation, recursively handling nested types

	This function reconstructs Pydantic models, dataclasses, and enums from JSON dicts
	without running validation logic. It recursively parses nested fields to ensure
	complete type fidelity.
	"""
	try:
		if data is None:
			return None

		origin = get_origin(annotation)
		args = get_args(annotation)

		# Handle Union types
		if origin is Union or (hasattr(annotation, '__class__') and annotation.__class__.__name__ == 'UnionType'):
			union_args = args or getattr(annotation, '__args__', [])
			for arg in union_args:
				if arg is type(None) and data is None:
					return None
				if arg is not type(None):
					try:
						return _parse_with_type_annotation(data, arg)
					except Exception:
						continue
			return data

		# Handle List types
		if origin is list:
			if not isinstance(data, list):
				return data
			if args:
				return [_parse_with_type_annotation(item, args[0]) for item in data]
			return data

		# Handle Tuple types (JSON serializes tuples as lists)
		if origin is tuple:
			if not isinstance(data, (list, tuple)):
				return data
			if args:
				# Parse each element according to its type annotation
				parsed_items = []
				for i, item in enumerate(data):
					# Use the corresponding type arg, or the last one if fewer args than items
					type_arg = args[i] if i < len(args) else args[-1] if args else Any
					parsed_items.append(_parse_with_type_annotation(item, type_arg))
				return tuple(parsed_items)
			return tuple(data) if isinstance(data, list) else data

		# Handle Dict types
		if origin is dict:
			if not isinstance(data, dict):
				return data
			if len(args) == 2:
				return {_parse_with_type_annotation(k, args[0]): _parse_with_type_annotation(v, args[1]) for k, v in data.items()}
			return data

		# Handle Enum types
		if inspect.isclass(annotation) and issubclass(annotation, enum.Enum):
			if isinstance(data, str):
				try:
					return annotation[data]  # By name
				except KeyError:
					return annotation(data)  # By value
			return annotation(data)  # By value

		# Handle Pydantic v2 - use model_construct to skip validation and recursively parse nested fields
		if hasattr(annotation, 'model_construct'):
			if not isinstance(data, dict):
				return data
			# Recursively parse each field according to its type annotation
			if hasattr(annotation, 'model_fields'):
				parsed_fields = {}
				for field_name, field_info in annotation.model_fields.items():
					if field_name in data:
						field_annotation = field_info.annotation
						parsed_fields[field_name] = _parse_with_type_annotation(data[field_name], field_annotation)
				return annotation.model_construct(**parsed_fields)
			# Fallback if model_fields not available
			return annotation.model_construct(**data)

		# Handle Pydantic v1 - use construct to skip validation and recursively parse nested fields
		if hasattr(annotation, 'construct'):
			if not isinstance(data, dict):
				return data
			# Recursively parse each field if __fields__ is available
			if hasattr(annotation, '__fields__'):
				parsed_fields = {}
				for field_name, field_obj in annotation.__fields__.items():
					if field_name in data:
						field_annotation = field_obj.outer_type_
						parsed_fields[field_name] = _parse_with_type_annotation(data[field_name], field_annotation)
				return annotation.construct(**parsed_fields)
			# Fallback if __fields__ not available
			return annotation.construct(**data)

		# Handle dataclasses
		if dataclasses.is_dataclass(annotation) and isinstance(data, dict):
			# Get field type annotations
			field_types = {f.name: f.type for f in dataclasses.fields(annotation)}
			# Recursively parse each field
			parsed_fields = {}
			for field_name, field_type in field_types.items():
				if field_name in data:
					parsed_fields[field_name] = _parse_with_type_annotation(data[field_name], field_type)
			return cast(type[Any], annotation)(**parsed_fields)

		# Handle regular classes
		if inspect.isclass(annotation) and isinstance(data, dict):
			try:
				return annotation(**data)
			except Exception:
				pass

		return data

	except Exception:
		return data
