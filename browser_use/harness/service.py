"""Harness-backed Agent: the browser_use Agent surface over browser-harness.

Same contract as browser_use.Agent, different engine -- the harness daemon
driving Chrome over CDP. Follows the browser_use.beta pattern: identical
surface, opt-in by import path.
"""

import asyncio
import json
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Generic

from browser_harness.sdk import Browser
from pydantic import BaseModel

from browser_use.agent.views import (
	ActionResult,
	AgentHistory,
	AgentHistoryList,
	AgentOutput,
	AgentStructuredOutput,
	StepMetadata,
)
from browser_use.browser.views import BrowserStateHistory
from browser_use.harness.dom import HarnessDomService
from browser_use.harness.tools import Tools
from browser_use.harness.views import HarnessState
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import (
	BaseMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	ImageURL,
	SystemMessage,
	UserMessage,
)

AgentHookFunc = Callable[['Agent'], Awaitable[None]]

_SYSTEM_PROMPT_PATH = Path(__file__).parent / 'system_prompt.md'


class Agent(Generic[AgentStructuredOutput]):
	def __init__(
		self,
		task: str,
		llm: BaseChatModel | None = None,
		*,
		browser: Browser | None = None,
		browser_session: Browser | None = None,
		tools: Tools | None = None,
		controller: Tools | None = None,
		output_model_schema: type[AgentStructuredOutput] | None = None,
		use_vision: bool = True,
		use_thinking: bool = True,
		max_actions_per_step: int = 4,
		max_failures: int = 3,
		step_timeout: int = 120,
		max_history_items: int = 16,
		extend_system_message: str | None = None,
		override_system_message: str | None = None,
		save_screenshots: bool = True,
		file_dir: str | Path | None = None,
		screenshots_dir: str | Path | None = None,
		**kwargs,
	):
		assert task and isinstance(task, str), 'task must be a non-empty string'
		if browser is not None and browser_session is not None:
			raise ValueError('Cannot specify both "browser" and "browser_session" parameters. Use "browser" for the cleaner API.')
		if tools is not None and controller is not None:
			raise ValueError('Cannot specify both "tools" and "controller" parameters. Use "tools" for the cleaner API.')

		self.task = task
		self._llm = llm
		self.browser = browser or browser_session or Browser()
		self.tools = tools or controller or Tools()
		self.output_model_schema = output_model_schema
		self.use_vision = use_vision
		self.use_thinking = use_thinking
		self.max_actions_per_step = max_actions_per_step
		self.max_failures = max_failures
		self.step_timeout = step_timeout
		self.max_history_items = max_history_items
		self.extend_system_message = extend_system_message
		self.override_system_message = override_system_message
		self.save_screenshots = save_screenshots

		if output_model_schema is not None and self.tools.get_output_model() is not output_model_schema:
			self.tools.use_structured_output_action(output_model_schema)
			self.task = self._enhance_task_with_schema(self.task, output_model_schema)

		self.dom_service = HarnessDomService(self.browser)
		self.ActionModel = self.tools.create_action_model()
		if self.use_thinking:
			self.AgentOutput = AgentOutput.type_with_custom_actions(self.ActionModel)
		else:
			self.AgentOutput = AgentOutput.type_with_custom_actions_no_thinking(self.ActionModel)

		self.history: AgentHistoryList[AgentStructuredOutput] = AgentHistoryList(history=[])
		self._step_notes: list[str] = []
		self._consecutive_failures = 0
		self._screenshot_dir: Path | None = Path(screenshots_dir) if screenshots_dir else None
		# the agent's persistence channel (write_file/read_file) -- without it,
		# extractions larger than the context window are unrecoverable
		self.file_dir: Path = Path(file_dir) if file_dir else Path(tempfile.mkdtemp(prefix='harness_agent_files_'))
		self._pending_results_text: str | None = None
		self._last_action_key: str | None = None
		self._repeat_count = 0

	@property
	def llm(self) -> BaseChatModel:
		if self._llm is None:
			from browser_use.llm.browser_use.chat import ChatBrowserUse

			self._llm = ChatBrowserUse()
		return self._llm

	@staticmethod
	def _enhance_task_with_schema(task: str, schema: type[BaseModel]) -> str:
		return f'{task}\n\nExpected output format: {schema.__name__}\n{json.dumps(schema.model_json_schema())}'

	# --- prompt assembly ---

	def _system_prompt(self) -> SystemMessage:
		if self.override_system_message is not None:
			text = self.override_system_message
		else:
			text = (
				_SYSTEM_PROMPT_PATH.read_text(encoding='utf-8')
				.replace('__MAX_ACTIONS__', str(self.max_actions_per_step))
				.replace('__ACTIONS__', self.tools.get_prompt_description())
			)
			if self.extend_system_message:
				text += f'\n{self.extend_system_message}'
		return SystemMessage(content=text, cache=True)

	def _state_message(self, state: HarnessState, step: int, max_steps: int) -> UserMessage:
		if state.dialog is not None:
			text = (
				f'Step {step}/{max_steps}\n'
				f'A native dialog is OPEN and the page is frozen: {json.dumps(state.dialog)}\n'
				'You must call handle_dialog before any other action.'
			)
			return UserMessage(content=text)
		tabs = '\n'.join(f'[{t.target_id[-4:]}] {t.title or "(untitled)"} — {t.url}' for t in state.tabs) or '(none)'
		text = (
			f'Step {step}/{max_steps}\n'
			f'Current URL: {state.url}\n'
			f'Title: {state.title}\n'
			f'Open tabs:\n{tabs}\n\n'
			f'Interactive elements:\n{state.elements_text()}\n\n'
			f'Page text excerpt:\n{state.text_excerpt or "(empty)"}'
		)
		if state.screenshot_b64 is None:
			return UserMessage(content=text)
		return UserMessage(
			content=[
				ContentPartTextParam(text=text),
				ContentPartImageParam(image_url=ImageURL(url=f'data:image/png;base64,{state.screenshot_b64}')),
			]
		)

	def _messages(self, state: HarnessState, step: int, max_steps: int) -> list[BaseMessage]:
		notes = self._step_notes[-self.max_history_items :]
		history_block: list[BaseMessage] = []
		if notes:
			history_block.append(UserMessage(content='Previous steps:\n' + '\n'.join(notes)))
		if self._pending_results_text:
			# last step's results IN FULL, once -- losing these forced agents to
			# re-extract the same page dozens of times
			history_block.append(UserMessage(content=f'Full result of your previous action(s):\n{self._pending_results_text}'))
		extra = []
		remaining = max_steps - step
		if self._repeat_count >= 3:
			extra.append(
				f'WARNING: you have repeated the same action {self._repeat_count} times with the same outcome. '
				'It will not work. Take a DIFFERENT approach.'
			)
		if remaining <= max(3, max_steps // 10):
			extra.append(
				f'URGENT: only {remaining} steps remain. Stop gathering. Read any workspace files you need and call '
				'`done` NOW with the best answer you have — a partial answer scores, an empty one does not.'
			)
		state_message = self._state_message(state, step, max_steps)
		if extra:
			prefix = '\n'.join(extra) + '\n\n'
			if isinstance(state_message.content, str):
				state_message = UserMessage(content=prefix + state_message.content)
			else:
				state_message = UserMessage(content=[ContentPartTextParam(text=prefix), *state_message.content])
		return [
			self._system_prompt(),
			UserMessage(content=f'Your task: {self.task}', cache=True),
			*history_block,
			state_message,
		]

	# --- execution ---

	async def _multi_act(self, actions: list, state: HarnessState) -> list[ActionResult]:
		results: list[ActionResult] = []
		for i, action in enumerate(actions[: self.max_actions_per_step]):
			result = await self.tools.act(action, browser=self.browser, state=state, file_dir=self.file_dir)
			results.append(result)
			self._track_repeat(action)
			if result.is_done or result.error is not None:
				break
			action_name = next(iter({k: v for k, v in action.model_dump(exclude_unset=True).items() if v is not None}), '')
			if self.tools.is_terminating(action_name) and i < len(actions) - 1:
				results.append(ActionResult(extracted_content=f'{action_name} changed the page — remaining actions skipped'))
				break
			# abort on unexpected page change -- later actions reference stale indices
			if i < len(actions) - 1 and state.dialog is None:
				try:
					info = await self.browser.page_info()
					if info.dialog is not None or info.url != state.url:
						results.append(ActionResult(extracted_content='Page changed — remaining actions skipped'))
						break
				except Exception:
					break
		return results

	def _record_step(
		self, state: HarnessState, output: AgentOutput | None, results: list[ActionResult], step: int, started: float
	) -> None:
		screenshot_path = None
		if output is not None and state.screenshot_b64 and self.save_screenshots:
			if self._screenshot_dir is None:
				self._screenshot_dir = Path(tempfile.mkdtemp(prefix='harness_agent_'))
			screenshot_path = str(self._screenshot_dir / f'step_{step}.png')
			import base64

			Path(screenshot_path).write_bytes(base64.b64decode(state.screenshot_b64))
		browser_state = BrowserStateHistory(
			url=state.url,
			title=state.title,
			tabs=state.tabs,
			interacted_element=[None] * len(output.action) if output is not None else [None],
			screenshot_path=screenshot_path,
		)
		self.history.add_item(
			AgentHistory(
				model_output=output,
				result=results,
				state=browser_state,
				metadata=StepMetadata(step_start_time=started, step_end_time=time.time(), step_number=step),
			)
		)
		if output is not None:
			acted = ', '.join(
				name for a in output.action for name, v in a.model_dump(exclude_unset=True).items() if v is not None
			)
			outcome = '; '.join(filter(None, ((r.error and f'ERROR: {r.error}') or r.extracted_content for r in results)))
			self._step_notes.append(f'Step {step}: goal={output.next_goal or "-"} | actions=[{acted}] | {outcome[:1200]}')
			# full results travel to the NEXT prompt exactly once; notes keep the compressed trail
			full = '\n'.join(r.extracted_content for r in results if r.extracted_content)
			self._pending_results_text = full[:60000] if full else None

	def _track_repeat(self, action) -> None:
		key = json.dumps(action.model_dump(exclude_unset=True), sort_keys=True, default=str)
		if key == self._last_action_key:
			self._repeat_count += 1
		else:
			self._last_action_key = key
			self._repeat_count = 0

	async def _step(self, step: int, max_steps: int) -> bool:
		"""Run one step. Returns True when the task is done."""
		started = time.time()
		try:
			state = await self.dom_service.get_state(include_screenshot=self.use_vision)
		except Exception:
			# transient capture failures (mid-navigation, slow page) shouldn't
			# burn a whole step -- retry once before giving up
			await asyncio.sleep(1.5)
			state = await self.dom_service.get_state(include_screenshot=self.use_vision)
		response = await self.llm.ainvoke(self._messages(state, step, max_steps), output_format=self.AgentOutput)
		output = response.completion
		results = await self._multi_act(output.action, state)
		self._record_step(state, output, results, step, started)
		if results and all(r.error is not None for r in results):
			self._consecutive_failures += 1
		else:
			self._consecutive_failures = 0
		return any(r.is_done for r in results)

	async def run(
		self,
		max_steps: int = 100,
		on_step_start: AgentHookFunc | None = None,
		on_step_end: AgentHookFunc | None = None,
	) -> AgentHistoryList[AgentStructuredOutput]:
		assert max_steps > 0
		await self.browser.start()
		try:
			for step in range(1, max_steps + 1):
				if on_step_start is not None:
					await on_step_start(self)
				try:
					done = await asyncio.wait_for(self._step(step, max_steps), timeout=self.step_timeout)
				except TimeoutError:
					self._consecutive_failures += 1
					self._record_failure(f'Step {step} timed out after {self.step_timeout}s', step)
					done = False
					await asyncio.sleep(2.0)  # a dead transport must not burn 3 strikes in 1ms
				except Exception as e:
					self._consecutive_failures += 1
					self._record_failure(f'Step {step} failed: {type(e).__name__}: {e}', step)
					done = False
					await asyncio.sleep(2.0)
				if on_step_end is not None:
					await on_step_end(self)
				if done:
					break
				if self._consecutive_failures >= self.max_failures:
					self._record_failure(f'Stopping after {self.max_failures} consecutive failures', step)
					break
			else:
				self._record_failure('Failed to complete task in maximum steps', max_steps)
		finally:
			await self.browser.stop()
		if self.output_model_schema is not None:
			self.history._output_model_schema = self.output_model_schema
		return self.history

	def run_sync(
		self,
		max_steps: int = 100,
		on_step_start: AgentHookFunc | None = None,
		on_step_end: AgentHookFunc | None = None,
	) -> AgentHistoryList[AgentStructuredOutput]:
		return asyncio.run(self.run(max_steps=max_steps, on_step_start=on_step_start, on_step_end=on_step_end))

	def _record_failure(self, message: str, step: int) -> None:
		now = time.time()
		self.history.add_item(
			AgentHistory(
				model_output=None,
				result=[ActionResult(error=message)],
				state=BrowserStateHistory(url='', title='', tabs=[], interacted_element=[None], screenshot_path=None),
				metadata=StepMetadata(step_start_time=now, step_end_time=now, step_number=step),
			)
		)
		self._step_notes.append(f'Step {step}: {message}')
