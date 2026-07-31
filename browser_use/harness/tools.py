"""Action registry for the harness-backed agent.

Mirrors the browser_use.tools API but executes against a browser_harness Browser.
Special params injected by name, invisible to the LLM: `browser` (the session)
and `state` (the observation the LLM acted on, for index -> element).
"""

import asyncio
import inspect
import json
from collections.abc import Callable
from typing import Any, Optional

from browser_harness.sdk import Browser, Element, HarnessError
from pydantic import BaseModel, ConfigDict, Field, create_model

from browser_use.agent.views import ActionResult
from browser_use.harness.views import HarnessState
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.views import StructuredOutputAction

SPECIAL_PARAMS = ('browser', 'state')

_MODIFIERS = {'alt': 1, 'control': 2, 'ctrl': 2, 'meta': 4, 'cmd': 4, 'command': 4, 'shift': 8}


class RegisteredHarnessAction(BaseModel):
	model_config = ConfigDict(arbitrary_types_allowed=True)

	name: str
	description: str
	function: Callable
	param_model: type[BaseModel]
	terminates_sequence: bool = False

	def prompt_description(self) -> str:
		schema = self.param_model.model_json_schema()
		params = []
		for param_name, param_info in schema.get('properties', {}).items():
			desc = param_name
			if 'type' in param_info:
				desc += f'={param_info["type"]}'
			if 'description' in param_info:
				desc += f' ({param_info["description"]})'
			params.append(desc)
		return f'{self.name}: {self.description}.' + (f' ({", ".join(params)})' if params else '')


class Tools:
	"""Registry of harness actions. `Controller` is an alias, as in browser_use."""

	def __init__(self, exclude_actions: list[str] | None = None, output_model: type[BaseModel] | None = None):
		self.registry: dict[str, RegisteredHarnessAction] = {}
		self._exclude_actions = set(exclude_actions or [])
		self._output_model: type[BaseModel] | None = None
		self._register_builtins()
		if output_model is not None:
			self.use_structured_output_action(output_model)

	# --- registration ---

	def action(self, description: str, param_model: type[BaseModel] | None = None, terminates_sequence: bool = False):
		"""Register an async function; LLM-visible schema = signature minus special params."""

		def decorator(func: Callable) -> Callable:
			assert inspect.iscoroutinefunction(func), f'action {func.__name__} must be async'
			if func.__name__ in self._exclude_actions:
				return func
			model = param_model or self._model_from_signature(func)
			self.registry[func.__name__] = RegisteredHarnessAction(
				name=func.__name__,
				description=description,
				function=func,
				param_model=model,
				terminates_sequence=terminates_sequence,
			)
			return func

		return decorator

	@staticmethod
	def _model_from_signature(func: Callable) -> type[BaseModel]:
		fields: dict[str, Any] = {}
		for name, param in inspect.signature(func).parameters.items():
			if name in SPECIAL_PARAMS:
				continue
			if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
				raise ValueError(f'action {func.__name__} may not use *args/**kwargs')
			annotation = param.annotation if param.annotation is not inspect.Parameter.empty else str
			default = param.default if param.default is not inspect.Parameter.empty else ...
			fields[name] = (annotation, default)
		return create_model(f'{func.__name__}_parameters', __base__=ActionModel, **fields)

	def exclude_action(self, action_name: str) -> None:
		self.registry.pop(action_name, None)

	def use_structured_output_action(self, output_model: type[BaseModel]) -> None:
		"""Re-register `done` so the final answer carries a typed payload."""
		self._output_model = output_model
		self.registry.pop('done', None)

		@self.action(
			'Complete the task. Set success=false if the task could not be completed. '
			'`data` MUST match the requested output schema exactly',
			param_model=StructuredOutputAction[output_model],
		)
		async def done(params: StructuredOutputAction) -> ActionResult:  # type: ignore[type-arg]
			data = params.data
			content = data.model_dump_json() if isinstance(data, BaseModel) else json.dumps(data)
			return ActionResult(is_done=True, success=params.success, extracted_content=content)

	def get_output_model(self) -> type[BaseModel] | None:
		return self._output_model

	# --- LLM plumbing ---

	def create_action_model(self) -> type[ActionModel]:
		"""One model, one optional field per action -- exactly one may be set."""
		fields = {
			name: (Optional[action.param_model], Field(default=None, description=action.description))
			for name, action in self.registry.items()
		}
		return create_model('HarnessActionModel', __base__=ActionModel, **fields)  # type: ignore[call-overload]

	def get_prompt_description(self) -> str:
		return '\n'.join(a.prompt_description() for a in self.registry.values())

	# --- execution ---

	async def act(self, action: ActionModel, browser: Browser, state: HarnessState | None = None) -> ActionResult:
		data = {k: v for k, v in action.model_dump(exclude_unset=True).items() if v is not None}
		assert len(data) == 1, f'action must set exactly one field, got {sorted(data)}'
		(name, params) = next(iter(data.items()))
		registered = self.registry.get(name)
		if registered is None:
			return ActionResult(error=f'Unknown action: {name}')
		try:
			validated = registered.param_model(**params)
		except Exception as e:
			return ActionResult(error=f'Invalid params for {name}: {e}')
		kwargs: dict[str, Any] = {}
		signature_params = inspect.signature(registered.function).parameters
		if 'browser' in signature_params:
			kwargs['browser'] = browser
		if 'state' in signature_params:
			kwargs['state'] = state
		if 'params' in signature_params:
			kwargs['params'] = validated
		else:
			kwargs.update({k: getattr(validated, k) for k in type(validated).model_fields})
		try:
			result = await registered.function(**kwargs)
		except HarnessError as e:
			return ActionResult(error=str(e))
		if isinstance(result, ActionResult):
			return result
		if isinstance(result, str):
			return ActionResult(extracted_content=result)
		if result is None:
			return ActionResult()
		raise ValueError(f'action {name} returned invalid type {type(result)}')

	def is_terminating(self, action_name: str) -> bool:
		registered = self.registry.get(action_name)
		return bool(registered and registered.terminates_sequence)

	# --- built-ins ---

	def _register_builtins(self) -> None:
		@self.action('Navigate to a URL (set new_tab=true to open it in a new tab)', terminates_sequence=True)
		async def navigate(url: str, new_tab: bool = False, browser: Browser = None) -> str:  # type: ignore[assignment]
			if new_tab:
				await browser.new_tab(url)
			else:
				await browser.goto_url(url)
			await browser.wait_for_load(timeout=10.0)
			return f'Navigated to {url}' + (' in new tab' if new_tab else '')

		@self.action('Go back to the previous page', terminates_sequence=True)
		async def go_back(browser: Browser = None) -> str:  # type: ignore[assignment]
			await browser.js('history.back()')
			await browser.wait_for_load(timeout=10.0)
			return 'Went back'

		@self.action('Click an interactive element by its index')
		async def click(index: int, browser: Browser = None, state: HarnessState = None) -> ActionResult:  # type: ignore[assignment]
			element = _resolve(state, index)
			if element is None:
				return ActionResult(error=f'Element index {index} not found in current state')
			await Element(browser, backend_node_id=element.backend_node_id, role=element.role, name=element.name).click()
			return ActionResult(extracted_content=f'Clicked {element.prompt_line()}')

		@self.action('Type text into an input element by its index (clears existing text unless clear=false)')
		async def input(  # noqa: A001 - mirrors the browser_use action name
			index: int,
			text: str,
			clear: bool = True,
			browser: Browser = None,  # type: ignore[assignment]
			state: HarnessState = None,  # type: ignore[assignment]
		) -> ActionResult:
			element = _resolve(state, index)
			if element is None:
				return ActionResult(error=f'Element index {index} not found in current state')
			await Element(browser, backend_node_id=element.backend_node_id, role=element.role, name=element.name).fill(
				text, clear_first=clear
			)
			return ActionResult(extracted_content=f'Typed {text!r} into {element.prompt_line()}')

		@self.action('Scroll the page by a number of viewport heights (negative = up)')
		async def scroll(pages: float = 1.0, browser: Browser = None) -> str:  # type: ignore[assignment]
			await browser.js(f'window.scrollBy(0, Math.round(innerHeight * {pages}))')
			return f'Scrolled {pages} pages'

		@self.action('Press a key or shortcut, e.g. "Enter", "Escape", "Control+a", "Meta+Enter"')
		async def send_keys(keys: str, browser: Browser = None) -> str:  # type: ignore[assignment]
			*mods, key = keys.split('+') if '+' in keys and keys != '+' else [keys]
			modifiers = 0
			for mod in mods:
				bit = _MODIFIERS.get(mod.strip().lower())
				if bit is None:
					return f'Unknown modifier {mod!r} in {keys!r}'
				modifiers |= bit
			await browser.press_key(key.strip(), modifiers=modifiers)
			return f'Sent keys {keys}'

		@self.action('Switch to another tab by its 4-character id', terminates_sequence=True)
		async def switch_tab(tab_id: str, browser: Browser = None) -> ActionResult:  # type: ignore[assignment]
			tab = await _tab_by_id(browser, tab_id)
			if tab is None:
				return ActionResult(error=f'No tab with id {tab_id}')
			await browser.switch_tab(tab)
			return ActionResult(extracted_content=f'Switched to tab {tab_id} ({tab.url})')

		@self.action('Close a tab by its 4-character id', terminates_sequence=True)
		async def close_tab(tab_id: str, browser: Browser = None) -> ActionResult:  # type: ignore[assignment]
			tab = await _tab_by_id(browser, tab_id)
			if tab is None:
				return ActionResult(error=f'No tab with id {tab_id}')
			await browser.close_tab(tab)
			await browser.ensure_real_tab()
			return ActionResult(extracted_content=f'Closed tab {tab_id}')

		@self.action('Read the full visible text of the current page')
		async def extract_text(browser: Browser = None) -> ActionResult:  # type: ignore[assignment]
			text = str((await browser.js('document.body ? document.body.innerText.slice(0, 20000) : ""')) or '')
			return ActionResult(extracted_content=text, include_extracted_content_only_once=True)

		@self.action('Evaluate a JavaScript expression on the page and return its JSON-serializable result')
		async def evaluate(expression: str, browser: Browser = None) -> ActionResult:  # type: ignore[assignment]
			value = await browser.js(expression)
			rendered = json.dumps(value, default=str)
			if len(rendered) > 4000:
				rendered = rendered[:4000] + '…(truncated)'
			return ActionResult(extracted_content=rendered)

		@self.action('Wait for the page to settle (seconds, max 10)')
		async def wait(seconds: float = 2.0, browser: Browser = None) -> str:  # type: ignore[assignment]
			await asyncio.sleep(min(max(seconds, 0.0), 10.0))
			return f'Waited {seconds}s'

		@self.action(
			'Accept or dismiss the currently open native dialog (alert/confirm/prompt). '
			'Required before anything else works while a dialog is open'
		)
		async def handle_dialog(accept: bool = True, prompt_text: str = '', browser: Browser = None) -> str:  # type: ignore[assignment]
			await browser.cdp(
				'Page.handleJavaScriptDialog', accept=accept, **({'promptText': prompt_text} if prompt_text else {})
			)
			return f'Dialog {"accepted" if accept else "dismissed"}'

		@self.action('Complete the task — call when done or when the task is impossible. `text` is the final answer')
		async def done(text: str, success: bool = True) -> ActionResult:
			return ActionResult(is_done=True, success=success, extracted_content=text)


def _resolve(state: HarnessState | None, index: int):
	if state is None:
		return None
	return state.selector_map.get(index)


async def _tab_by_id(browser: Browser, tab_id: str):
	for tab in await browser.list_tabs():
		if tab.target_id[-4:] == tab_id or tab.target_id == tab_id:
			return tab
	return None


Controller = Tools
