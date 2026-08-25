"""Action registry for the harness-backed agent.

Mirrors the browser_use.tools API but executes against a browser_harness Browser.
Special params injected by name, invisible to the LLM: `browser` (the session),
`state` (the observation the LLM acted on, for index -> element) and
`file_dir` (workspace for write_file/read_file -- the agent's persistence
channel, without which bulk extractions can't survive the context window).
"""

import asyncio
import difflib
import inspect
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote_plus

from browser_harness.sdk import Browser, Element, HarnessError
from pydantic import BaseModel, ConfigDict, Field, create_model

from browser_use.agent.views import ActionResult
from browser_use.harness.views import HarnessState
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.views import StructuredOutputAction

SPECIAL_PARAMS = ('browser', 'state', 'file_dir', 'page_extraction_llm')

_MODIFIERS = {'alt': 1, 'control': 2, 'ctrl': 2, 'meta': 4, 'cmd': 4, 'command': 4, 'shift': 8}

# js evaluations may legitimately run long (in-page fetch loops); the step
# budget, not the IPC default, should bound them
JS_TIMEOUT_S = 90.0  # must stay well under the agent's step timeout or one eval eats the step
EVALUATE_DISPLAY_CAP = 15000
EXTRACT_DISPLAY_CAP = 30000


def _safe_file(file_dir: Path | None, file_name: str) -> Path:
	if file_dir is None:
		raise HarnessError('no file workspace configured')
	name = Path(file_name).name  # no traversal
	if not name:
		raise HarnessError(f'invalid file name {file_name!r}')
	file_dir.mkdir(parents=True, exist_ok=True)
	return file_dir / name


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
		self._read_files: set[str] = set()
		self._written_files: set[str] = set()
		self._done_refused = False
		self._completeness_refused = False
		self._task = ''
		self._steps_remaining: int | None = None
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

	def set_budget(self, steps_remaining: int) -> None:
		"""Let `done` checks know how much room is left to act on a refusal."""
		self._steps_remaining = steps_remaining

	def set_task(self, task: str) -> None:
		"""Give the registry the task text so `done` can check it for completeness."""
		self._task = task

	def _completeness_refusal(self, validated: BaseModel) -> ActionResult | None:
		"""Refuse a `done` that delivers fewer items than the task demanded.

		Traced losses: "required exactly 6 jobs with 3 LinkedIn and 3 Glassdoor"
		answered with 2; "Simyo only has 40GB and 30GB while other tiers were not
		completed". One-shot, like the unread-evidence check.
		"""
		if self._completeness_refused or not getattr(self, '_task', ''):
			return None
		# never refuse near the budget end: a partial answer scores, an empty one
		# does not, and one traced task lost its whole answer to this gate
		if self._steps_remaining is not None and self._steps_remaining < 6:
			return None
		wanted = _required_counts(self._task)
		if not wanted:
			return None
		text = json.dumps(validated.model_dump(), default=str)
		delivered = _count_items(text)
		if delivered is None:  # unstructured prose -- counting it is guesswork
			return None
		target = max(wanted)
		if delivered >= target:
			return None
		self._completeness_refused = True
		return ActionResult(
			error=(
				f'The task asks for {target} items but your answer appears to contain about {delivered}. '
				'Collect the rest (read your workspace files if the data is there), then call done. '
				'If the source genuinely has no more, say so explicitly and call done again.'
			)
		)

	def _unread_evidence_refusal(self, validated: BaseModel, file_dir: Path | None) -> ActionResult | None:
		"""Refuse a `done` that declares data unavailable while unread files may hold it.

		Traced failures shipped "not available" for fields sitting in the agent's
		own saved files. One-shot: a second consecutive done goes through.
		"""
		if self._done_refused:
			return None
		if self._steps_remaining is not None and self._steps_remaining < 6:
			return None
		text = json.dumps(validated.model_dump(), default=str).lower()
		if not any(marker in text for marker in _UNAVAILABLE_MARKERS):
			return None
		unread = _unread_evidence(self._read_files, file_dir)
		if not unread:
			return None
		self._done_refused = True
		return ActionResult(
			error=(
				f'You marked fields unavailable but have not read these workspace files: {unread}. '
				'They may contain exactly those values — read_file them, then call done with the complete answer. '
				'(Call done again next step if they genuinely do not help.)'
			)
		)

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

	async def act(
		self,
		action: ActionModel,
		browser: Browser,
		state: HarnessState | None = None,
		file_dir: Path | None = None,
		page_extraction_llm: Any = None,
	) -> ActionResult:
		# browser_use semantics: execute the FIRST field that is set and ignore the
		# rest. Gemini fills every optional field of the action schema, so running
		# them all executed ~20 garbage actions per step and destroyed a whole eval.
		data = {k: v for k, v in action.model_dump(exclude_unset=True).items() if v is not None}
		if not data:
			return ActionResult(error='Action set no fields')
		name, params = next(iter(data.items()))
		return await self._act_one(name, params, browser, state, file_dir, page_extraction_llm)

	async def _act_one(
		self,
		name: str,
		params: dict,
		browser: Browser,
		state: HarnessState | None,
		file_dir: Path | None,
		page_extraction_llm: Any = None,
	) -> ActionResult:
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
		if 'file_dir' in signature_params:
			kwargs['file_dir'] = file_dir
		if 'page_extraction_llm' in signature_params:
			kwargs['page_extraction_llm'] = page_extraction_llm
		if 'params' in signature_params:
			kwargs['params'] = validated
		else:
			kwargs.update({k: getattr(validated, k) for k in type(validated).model_fields})
		if name == 'done':
			for check in (
				self._completeness_refusal(validated),
				self._unread_evidence_refusal(validated, file_dir),
			):
				if check is not None:
					return check
		try:
			result = await registered.function(**kwargs)
		except HarnessError as e:
			return ActionResult(error=_actionable_error(str(e)))
		if isinstance(result, ActionResult):
			return result
		if isinstance(result, str):
			return ActionResult(extracted_content=result)
		if result is None:
			return ActionResult()
		raise ValueError(f'action {name} returned invalid type {type(result)}')

	def __getattr__(self, name: str):
		"""Call any registered action directly, as browser_use.Tools does:

		    await tools.navigate(url="https://example.com", browser=browser)

		Deterministic scripting with no LLM in the loop.
		"""
		if name.startswith('_') or name not in self.registry:
			raise AttributeError(f'{type(self).__name__!r} object has no attribute {name!r}')

		async def call(
			browser: Browser,
			state: HarnessState | None = None,
			file_dir: Path | None = None,
			page_extraction_llm: Any = None,
			**params,
		):
			return await self._act_one(name, params, browser, state, file_dir, page_extraction_llm)

		call.__name__ = name
		return call

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

		@self.action('Search the web with a query', terminates_sequence=True)
		async def search(query: str, engine: str = 'google', browser: Browser = None) -> str:  # type: ignore[assignment]
			urls = {
				'google': 'https://www.google.com/search?q=',
				'bing': 'https://www.bing.com/search?q=',
				'duckduckgo': 'https://duckduckgo.com/?q=',
			}
			await browser.goto_url(urls.get(engine.lower(), urls['google']) + quote_plus(query))
			await browser.wait_for_load(timeout=10.0)
			return f'Searched {engine} for {query!r}'

		@self.action('Go back to the previous page', terminates_sequence=True)
		async def go_back(description: str = '', browser: Browser = None) -> str:  # type: ignore[assignment]
			await browser.js('history.back()')
			await browser.wait_for_load(timeout=10.0)
			return 'Went back'

		@self.action('Click an interactive element by its index')
		async def click(index: int, browser: Browser = None, state: HarnessState = None) -> ActionResult:  # type: ignore[assignment]
			element = _resolve(state, index)
			if element is None:
				return ActionResult(error=_index_error(index, state))
			handle = Element(browser, backend_node_id=element.backend_node_id, role=element.role, name=element.name)
			before = await _click_fingerprint(browser, handle)
			try:
				await handle.click()
			except HarnessError as e:
				if 'box model' not in str(e):
					raise
				# an <option> in a closed <select> has no box; guidance alone didn't
				# stop models retrying, so do the select for them
				outcome = await handle._call_on_node(_SELECT_BY_SELF_JS)
				if isinstance(outcome, str) and outcome.startswith('selected '):
					return ActionResult(extracted_content=f'{outcome} (via select_dropdown — the element had no clickable box)')
				raise
			await asyncio.sleep(0.25)
			after = await _click_fingerprint(browser, handle)
			if after and before and after.get('url') != before.get('url'):
				await browser.wait_for_load(timeout=10.0)
				return ActionResult(extracted_content=f'Clicked {element.prompt_line()} — navigated to {after["url"]}')
			if before and after and after == before:
				# unconditional "Clicked ..." success let one run click the same
				# dead radio 18 times; report the no-op instead
				blocker = after.get('hit')
				return ActionResult(
					extracted_content=f'Clicked {element.prompt_line()} — NO OBSERVABLE EFFECT: url, element state and page text '
					f'are unchanged.{f" The click landed on {blocker!r}." if blocker else ""} The control is probably covered or '
					'JS-driven: click its <label>, dismiss any overlay, or set the state via evaluate and dispatch input+change'
				)
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
				return ActionResult(error=_index_error(index, state))
			handle = Element(browser, backend_node_id=element.backend_node_id, role=element.role, name=element.name)
			await handle.fill(text, clear_first=clear)
			# verify -- autocomplete widgets silently append or rewrite; a false
			# "Typed ..." success once burned 30 steps on one field
			actual = await handle._call_on_node(
				"function(){if('value' in this && typeof this.value === 'string') return this.value;"
				'if(this.isContentEditable) return this.innerText;'
				'return null;}'
			)
			if actual is None:
				# unreadable field (rich-text editors like Trix): say so rather than
				# claiming success -- a silent no-op once cost 16 steps
				return ActionResult(
					extracted_content=f'Typed {text!r} into {element.prompt_line()} but COULD NOT VERIFY it took '
					'(the field exposes no readable value). Confirm on the page before relying on it'
				)
			if clear and actual != text:
				return ActionResult(
					error=f'input verification failed: field now contains {str(actual)[:200]!r}, expected {text!r}. '
					'The field is likely a controlled autocomplete — click its suggestion element, or set the value via evaluate'
				)
			return ActionResult(extracted_content=f'Typed {text!r} into {element.prompt_line()}')

		@self.action('Set the option of a <select> element by its visible text or value')
		async def select_dropdown(
			index: int,
			text: str,
			browser: Browser = None,  # type: ignore[assignment]
			state: HarnessState = None,  # type: ignore[assignment]
		) -> ActionResult:
			element = _resolve(state, index)
			if element is None:
				return ActionResult(error=_index_error(index, state))
			handle = Element(browser, backend_node_id=element.backend_node_id, role=element.role, name=element.name)
			# works whether index points at the <select> or an <option> inside it
			value = text
			outcome = await handle._call_on_node(
				'function(want){'
				"let s = this.tagName === 'SELECT' ? this : (this.tagName === 'OPTION' ? this.closest('select') : this.querySelector('select'));"
				"if (!s) return 'no <select> found for this element';"
				'const opt = [...s.options].find(o => o.value === want || o.text.trim() === want);'
				"if (!opt) return 'no option matching ' + JSON.stringify(want) + '; options: ' + [...s.options].map(o => o.text.trim()).slice(0, 30).join(' | ');"
				's.value = opt.value;'
				"s.dispatchEvent(new Event('input', {bubbles: true}));"
				"s.dispatchEvent(new Event('change', {bubbles: true}));"
				"return 'selected ' + opt.text.trim();}",
				value,
			)
			if isinstance(outcome, str) and outcome.startswith(('no ', 'no<')):
				return ActionResult(error=outcome)
			return ActionResult(extracted_content=str(outcome))

		@self.action('Scroll by pages. down=True scrolls down, False scrolls up; pages defaults to one viewport')
		async def scroll(down: bool = True, pages: float = 1.0, browser: Browser = None) -> str:  # type: ignore[assignment]
			delta = pages if down else -pages
			await browser.js(f'window.scrollBy(0, Math.round(innerHeight * {delta}))')
			return f'Scrolled {"down" if down else "up"} {pages} pages'

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

		@self.action(
			'Switch to another open tab by tab_id. Tab IDs are shown in the browser state tabs list (last 4 chars of target_id)',
			terminates_sequence=True,
		)
		async def switch(tab_id: str, browser: Browser = None) -> ActionResult:  # type: ignore[assignment]
			tab = await _tab_by_id(browser, tab_id)
			if tab is None:
				return ActionResult(error=f'No tab with id {tab_id}')
			await browser.switch_tab(tab)
			return ActionResult(extracted_content=f'Switched to tab {tab_id} ({tab.url})')

		@self.action(
			'Close a tab by tab_id. Use to clean up tabs you no longer need',
			terminates_sequence=True,
		)
		async def close(tab_id: str, browser: Browser = None) -> ActionResult:  # type: ignore[assignment]
			tab = await _tab_by_id(browser, tab_id)
			if tab is None:
				return ActionResult(error=f'No tab with id {tab_id}')
			await browser.close_tab(tab)
			await browser.ensure_real_tab()
			return ActionResult(extracted_content=f'Closed tab {tab_id}')

		@self.action(
			'PREFERRED way to gather data. Give `query` and the whole page is distilled to exactly what you asked for in '
			'one step, e.g. query="every listing title, price and rating". Leave query empty only for raw visible text. '
			'save_as writes the full result to a workspace file at the same time'
		)
		async def extract(
			query: str = '',
			save_as: str = '',
			browser: Browser = None,  # type: ignore[assignment]
			file_dir: Path = None,  # type: ignore[assignment]
			page_extraction_llm: Any = None,
		) -> ActionResult:
			text = str((await browser.js('document.body ? document.body.innerText.slice(0, 200000) : ""')) or '')
			if not text.strip():
				# chrome's PDF viewer has no readable body -- reporting "0 chars saved"
				# as success made agents re-try the same dead path for 20 steps
				url = str((await browser.js('location.href')) or '')
				if url.lower().endswith('.pdf') or await browser.js(
					'!!document.querySelector(\'embed[type="application/pdf"]\')'
				):
					return ActionResult(
						error='This is a PDF in the browser viewer — its text is not readable from the DOM. '
						'Fetch and parse it instead, e.g. evaluate a fetch of the PDF URL, or find an HTML version of the document'
					)
				return ActionResult(
					error='Page has no readable text yet (empty body). Wait for it to render, or the content may be in an iframe/canvas'
				)
			if query and page_extraction_llm is not None:
				extracted = await _extract_with_llm(page_extraction_llm, query, text)
				if extracted is not None:
					return _deliver(extracted, save_as, file_dir, EXTRACT_DISPLAY_CAP)
			return _deliver(text, save_as, file_dir, EXTRACT_DISPLAY_CAP)

		@self.action(
			'Evaluate a JavaScript expression on the page and return its JSON-serializable result. '
			'May run up to 150s. Set save_as to write the FULL result to a workspace file (shown output is capped)'
		)
		async def evaluate(
			code: str,
			save_as: str = '',
			browser: Browser = None,  # type: ignore[assignment]
			file_dir: Path = None,  # type: ignore[assignment]
		) -> ActionResult:
			value = await browser.js(code, timeout=JS_TIMEOUT_S)
			rendered = value if isinstance(value, str) else json.dumps(value, default=str)
			return _deliver(rendered, save_as, file_dir, EVALUATE_DISPLAY_CAP)

		@self.action(
			'Write text to a file in the workspace (append=true to accumulate). '
			'Use this to persist extracted data as you go — context is limited, files are not'
		)
		async def write_file(
			file_name: str,
			content: str,
			append: bool = False,
			file_dir: Path = None,  # type: ignore[assignment]
		) -> ActionResult:
			if not content.strip() or content.strip() in ('[]', '{}', 'null'):
				return ActionResult(
					error=f'Refusing to save empty content to {file_name}. Extract the data first, then write it — '
					'an empty artifact reads as a completed step but proves nothing'
				)
			path = _safe_file(file_dir, file_name)
			if append and path.exists():
				with path.open('a', encoding='utf-8') as f:
					f.write(content)
			else:
				path.write_text(content, encoding='utf-8')
			self._written_files.add(path.name)
			return ActionResult(
				extracted_content=f'{"Appended" if append else "Wrote"} {len(content)} chars to {path.name} (now {path.stat().st_size} bytes)',
				long_term_memory=f'{path.name}: {path.stat().st_size} bytes',
			)

		@self.action('Read a workspace file (offset/limit in characters) — use before done to assemble the final answer')
		async def read_file(
			file_name: str,
			offset: int = 0,
			limit: int = 30000,
			file_dir: Path = None,  # type: ignore[assignment]
		) -> ActionResult:
			path = _safe_file(file_dir, file_name)
			if not path.exists():
				existing = sorted(p.name for p in file_dir.iterdir()) if file_dir and file_dir.exists() else []
				close = difflib.get_close_matches(path.name, existing, n=1)
				hint = (
					f' Did you mean {close[0]!r}?'
					if close
					else ' You have not written any data yet — extract and write_file first.'
				)
				return ActionResult(error=f'No file {path.name!r}. Workspace files: {existing}.{hint}')
			self._read_files.add(path.name)
			content = path.read_text(encoding='utf-8', errors='replace')
			chunk = content[offset : offset + limit]
			suffix = (
				f'\n…({len(content) - offset - len(chunk)} more chars — read again with offset={offset + len(chunk)})'
				if offset + len(chunk) < len(content)
				else ''
			)
			return ActionResult(
				extracted_content=f'{path.name} [{offset}:{offset + len(chunk)} of {len(content)}]:\n{chunk}{suffix}',
				include_extracted_content_only_once=True,
			)

		@self.action('Wait for the page to settle (seconds, max 10)')
		async def wait(seconds: float = 2.0, browser: Browser = None) -> str:  # type: ignore[assignment]
			await asyncio.sleep(min(max(seconds, 0.0), 10.0))
			return f'Waited {seconds}s'

		@self.action(
			'Accept or dismiss the currently open native dialog (alert/confirm/prompt). '
			'Required before anything else works while a dialog is open'
		)
		async def handle_dialog(accept: bool = True, prompt_text: str = '', browser: Browser = None) -> str:  # type: ignore[assignment]
			if prompt_text:
				await browser.cdp('Page.handleJavaScriptDialog', accept=accept, promptText=prompt_text)
			else:
				await browser.cdp('Page.handleJavaScriptDialog', accept=accept)
			return f'Dialog {"accepted" if accept else "dismissed"}'

		@self.action('Upload a file to a file input by its element index')
		async def upload_file(
			index: int,
			path: str,
			browser: Browser = None,  # type: ignore[assignment]
			state: HarnessState = None,  # type: ignore[assignment]
		) -> ActionResult:
			element = _resolve(state, index)
			if element is None:
				return ActionResult(error=_index_error(index, state))
			await browser.cdp('DOM.setFileInputFiles', files=[path], backendNodeId=element.backend_node_id)
			return ActionResult(extracted_content=f'Uploaded {path} to {element.prompt_line()}')

		@self.action('Take a screenshot of the current viewport; with file_name, save it and return the path')
		async def screenshot(
			file_name: str = '',
			browser: Browser = None,  # type: ignore[assignment]
			file_dir: Path = None,  # type: ignore[assignment]
		) -> ActionResult:
			if file_name:
				path = await browser.capture_screenshot(_safe_file(file_dir, file_name))
				return ActionResult(
					extracted_content=f'Screenshot saved to {path.name}', long_term_memory=f'screenshot: {path.name}'
				)
			data = await browser.screenshot_b64(max_dim=1600)
			return ActionResult(
				extracted_content='Screenshot captured',
				images=[{'name': 'screenshot', 'data': data}],
			)

		@self.action('List the options of a <select> element by its index')
		async def dropdown_options(
			index: int,
			browser: Browser = None,  # type: ignore[assignment]
			state: HarnessState = None,  # type: ignore[assignment]
		) -> ActionResult:
			element = _resolve(state, index)
			if element is None:
				return ActionResult(error=_index_error(index, state))
			handle = Element(browser, backend_node_id=element.backend_node_id, role=element.role, name=element.name)
			options = await handle._call_on_node(
				'function(){'
				"const s = this.tagName === 'SELECT' ? this : (this.tagName === 'OPTION' ? this.closest('select') : this.querySelector('select'));"
				"if (!s) return JSON.stringify({error: 'no <select> found for this element'});"
				'return JSON.stringify([...s.options].map(o => ({text: o.text.trim(), value: o.value})));}'
			)
			return ActionResult(extracted_content=str(options))

		@self.action('Replace specific text within a workspace file — targeted edits without rewriting the file')
		async def replace_file(
			file_name: str,
			old_str: str,
			new_str: str,
			file_dir: Path = None,  # type: ignore[assignment]
		) -> ActionResult:
			path = _safe_file(file_dir, file_name)
			if not path.exists():
				return ActionResult(error=f'No file {path.name!r}')
			content = path.read_text(encoding='utf-8', errors='replace')
			if old_str not in content:
				return ActionResult(error=f'{old_str[:80]!r} not found in {path.name}')
			path.write_text(content.replace(old_str, new_str), encoding='utf-8')
			return ActionResult(extracted_content=f'Replaced {content.count(old_str)} occurrence(s) in {path.name}')

		@self.action('Scroll to the first occurrence of text on the page')
		async def find_text(text: str, browser: Browser = None) -> ActionResult:  # type: ignore[assignment]
			found = await browser.js(
				'(()=>{const want=' + json.dumps(text) + ';'
				'const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);'
				'while(w.nextNode()){if(w.currentNode.textContent.includes(want)){'
				'w.currentNode.parentElement.scrollIntoView({block:"center"});return true;}}return false;})()'
			)
			if not found:
				return ActionResult(error=f'Text {text!r} not found on the page')
			return ActionResult(extracted_content=f'Scrolled to {text!r}')

		@self.action('Search page text for a pattern like grep — zero LLM cost, returns matches with context')
		async def search_page(
			pattern: str,
			regex: bool = False,
			case_sensitive: bool = False,
			context_chars: int = 120,
			max_results: int = 20,
			browser: Browser = None,  # type: ignore[assignment]
		) -> ActionResult:
			text = str((await browser.js('document.body ? document.body.innerText : ""')) or '')
			flags = 0 if case_sensitive else re.IGNORECASE
			needle = pattern if regex else re.escape(pattern)
			try:
				matches = list(re.finditer(needle, text, flags))[:max_results]
			except re.error as e:
				return ActionResult(error=f'Invalid regex {pattern!r}: {e}')
			if not matches:
				return ActionResult(extracted_content=f'No matches for {pattern!r}')
			out = [f'…{text[max(0, m.start() - context_chars) : m.end() + context_chars].strip()}…' for m in matches]
			return ActionResult(extracted_content=f'{len(matches)} match(es) for {pattern!r}:\n' + '\n---\n'.join(out))

		@self.action('Query DOM elements by CSS selector — zero LLM cost, returns tag, text and attributes')
		async def find_elements(
			selector: str,
			max_results: int = 20,
			include_text: bool = True,
			browser: Browser = None,  # type: ignore[assignment]
		) -> ActionResult:
			result = await browser.js(
				'(()=>{const els=[...document.querySelectorAll(' + json.dumps(selector) + ')].slice(0,' + str(max_results) + ');'
				'return JSON.stringify(els.map(e=>({tag:e.tagName.toLowerCase(),'
				+ ('text:(e.innerText||"").trim().slice(0,200),' if include_text else '')
				+ 'attrs:Object.fromEntries([...e.attributes].map(a=>[a.name,a.value.slice(0,200)]))})));})()'
			)
			return ActionResult(extracted_content=str(result))

		@self.action(
			'Complete the task — call when done or when the task is impossible. `text` is the COMPLETE final answer '
			'with all requested data (read your workspace files first if the data lives there). '
			'A partial answer beats no answer: never let the run end without calling done'
		)
		async def done(text: str, success: bool = True) -> ActionResult:
			return ActionResult(is_done=True, success=success, extracted_content=text)


def _deliver(rendered: str, save_as: str, file_dir: Path | None, cap: int) -> ActionResult:
	"""Show up to `cap` chars; with save_as, persist the full text to the workspace."""
	saved = ''
	memory = None
	if save_as:
		path = _safe_file(file_dir, save_as)
		path.write_text(rendered, encoding='utf-8')
		saved = f' [full {len(rendered)} chars saved to {path.name}]'
		# the surviving note must say the rest is recoverable, or the model
		# answers from the truncated head and calls everything else unavailable
		memory = (
			f'{path.name}: {len(rendered)} chars — TRUNCATED in context, full content only via read_file("{path.name}")'
			if len(rendered) > cap
			else f'{path.name}: {len(rendered)} chars'
		)
	shown = (
		rendered
		if len(rendered) <= cap
		else rendered[:cap]
		+ f'…(TRUNCATED at {cap} of {len(rendered)} chars. '
		+ (f'read_file("{save_as}", offset={cap}) for the rest)' if save_as else 're-run with save_as=<file> to keep it all)')
	)
	return ActionResult(extracted_content=shown + saved, long_term_memory=memory, include_extracted_content_only_once=True)


_FINGERPRINT_JS = (
	'function(){'
	'const r = this.getBoundingClientRect();'
	'const el = document.elementFromPoint(r.left + r.width/2, r.top + r.height/2);'
	'return JSON.stringify({'
	'url: location.href,'
	'checked: this.checked ?? null,'
	'value: ("value" in this ? String(this.value).slice(0,120) : null),'
	'expanded: this.getAttribute("aria-expanded"),'
	'selected: this.getAttribute("aria-selected") ?? this.getAttribute("aria-checked"),'
	'len: document.body ? document.body.innerText.length : 0,'
	'hit: (el && el !== this && !this.contains(el)) ? (el.tagName + (el.className ? "." + String(el.className).split(" ")[0] : "")) : null'
	'});}'
)


async def _click_fingerprint(browser: Browser, handle: Element) -> dict | None:
	"""Cheap before/after evidence that a click actually did something."""
	try:
		raw = await handle._call_on_node(_FINGERPRINT_JS)
		return json.loads(raw) if isinstance(raw, str) else None
	except (HarnessError, ValueError):
		return None


# select the option this node IS (used when clicking it is impossible)
_SELECT_BY_SELF_JS = (
	'function(){'
	"if (this.tagName !== 'OPTION') return 'not an option';"
	"const s = this.closest('select');"
	"if (!s) return 'no parent select';"
	'this.selected = true;'
	's.value = this.value;'
	"s.dispatchEvent(new Event('input', {bubbles: true}));"
	"s.dispatchEvent(new Event('change', {bubbles: true}));"
	"return 'selected ' + this.text.trim();}"
)


async def _extract_with_llm(llm: Any, query: str, text: str) -> str | None:
	"""Distil page text to what the query asks for, as browser_use's extract does.
	Returns None on any failure so the caller falls back to the raw text."""
	from browser_use.llm.messages import UserMessage

	try:
		response = await llm.ainvoke(
			[
				UserMessage(
					content=(
						f'Extract exactly what this query asks for from the page content below. '
						f'Return the data itself (JSON or markdown table), no commentary. '
						f'If something asked for is absent, say so for that field rather than inventing it.\n\n'
						f'QUERY: {query}\n\nPAGE CONTENT:\n{text[:120000]}'
					)
				)
			]
		)
		return str(response.completion).strip() or None
	except Exception:
		return None


def _required_counts(task: str) -> list[int]:
	"""Numbers the task attaches to a quantity of results, e.g. "at least 40
	leads", "first 3 pages", "exactly 6 jobs", "top 10"."""
	pattern = r'\b(?:at least|atleast|minimum of|exactly|first|top|list|find|collect|extract)\s+(\d{1,3})\b'
	counts = [int(n) for n in re.findall(pattern, task, re.IGNORECASE)]
	return [n for n in counts if 2 <= n <= 200]


def _count_items(rendered: str) -> int | None:
	"""Item count of a final answer, or None when it is prose we cannot count.

	Returning None matters: guessing "about 1" for a prose answer that listed
	three findings produced a false refusal.
	"""
	objects = rendered.count('},{') + rendered.count('}, {')
	if objects:
		return objects + 1
	lines = [ln.strip() for ln in rendered.replace('\\n', '\n').splitlines() if ln.strip()]
	markers = sum(1 for ln in lines if re.match(r'^(?:[-*\u2022|]|\d{1,3}[.)])\s', ln))
	return markers if markers >= 2 else None


_UNAVAILABLE_MARKERS = ('not available', 'not shown', 'not captured', 'unavailable', 'could not extract')


def _unread_evidence(read_files: set[str], file_dir: Path | None) -> list[str]:
	if file_dir is None or not file_dir.exists():
		return []
	return sorted(
		p.name
		for p in file_dir.iterdir()
		if p.is_file() and p.name not in read_files and p.suffix.lower() not in ('.png', '.jpg', '.jpeg')
	)


def _actionable_error(error: str) -> str:
	"""Map raw CDP/harness errors to guidance the model can act on."""
	if 'Could not compute box model' in error:
		return (
			'Element has no rendered box — it is likely an <option> inside a closed <select> '
			'or an offscreen/hidden node. For dropdowns use select_dropdown; otherwise scroll or pick a different element'
		)
	if 'No node found for given backend id' in error:
		return 'Element reference is stale — the page changed since the last observation. Act on the CURRENT element list'
	return error


def _index_error(index: int, state: HarnessState | None) -> str:
	"""Out-of-range indices are usually the right index with digits appended
	(139 -> 1396582), so name the valid range and the likely intent."""
	if state is None or not state.elements:
		return f'Element index {index} not found — no interactive elements in the current state'
	valid = state.selector_map
	candidates = [i for i in valid if str(index).startswith(str(i)) and i != index]
	hint = f' Did you mean [{max(candidates)}]{valid[max(candidates)].prompt_line()}?' if candidates else ''
	return f'Element index {index} not found — valid indices are 1..{len(state.elements)}.{hint}'


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
