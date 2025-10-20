"""Code-use agent service - Jupiter notebook-like code execution for browser automation."""

import asyncio
import datetime
import logging
import re
import traceback
from pathlib import Path
from typing import Any

from uuid_extensions import uuid7str

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.dom.service import DomService
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	ImageURL,
	SystemMessage,
	UserMessage,
)
from browser_use.screenshots.service import ScreenshotService
from browser_use.tokens.service import TokenCost
from browser_use.tools.service import Tools

from .namespace import EvaluateError, create_namespace
from .views import ExecutionStatus, NotebookSession

logger = logging.getLogger(__name__)


def _truncate_message_content(content: str, max_length: int = 10000) -> str:
	"""Truncate message content to max_length characters for history."""
	if len(content) <= max_length:
		return content
	# Truncate and add marker
	return content[:max_length] + f'\n\n[... truncated {len(content) - max_length} characters for history]'


class CodeUseAgent:
	"""
	Agent that executes Python code in a notebook-like environment for browser automation.

	This agent provides a Jupiter notebook-like interface where the LLM writes Python code
	that gets executed in a persistent namespace with browser control functions available.
	"""

	def __init__(
		self,
		task: str,
		llm: BaseChatModel,
		browser_session: BrowserSession | None = None,
		browser_profile: BrowserProfile | None = None,
		tools: Tools | None = None,
		page_extraction_llm: BaseChatModel | None = None,
		file_system: FileSystem | None = None,
		available_file_paths: list[str] | None = None,
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		max_steps: int = 100,
		use_vision: bool = True,
		calculate_cost: bool = False,
		**kwargs,
	):
		"""
		Initialize the code-use agent.

		Args:
			task: The task description for the agent
			llm: The LLM to use for generating code
			browser_session: Optional browser session (will be created if not provided)
			browser_profile: Optional browser profile for creating a new session
			tools: Optional Tools instance (will create default if not provided)
			page_extraction_llm: Optional LLM for page extraction
			file_system: Optional file system for file operations
			available_file_paths: Optional list of available file paths
			sensitive_data: Optional sensitive data dictionary
			max_steps: Maximum number of execution steps
			use_vision: Whether to include screenshots in LLM messages (default: True)
			**kwargs: Additional keyword arguments for compatibility (ignored)
		"""
		# Log and ignore unknown kwargs for compatibility
		if kwargs:
			logger.debug(f'Ignoring additional kwargs for CodeUseAgent compatibility: {list(kwargs.keys())}')
		self.task = task
		self.llm = llm
		self.browser_session = browser_session
		self.browser_profile = browser_profile or BrowserProfile()
		self.tools = tools or Tools()
		self.page_extraction_llm = page_extraction_llm
		self.file_system = file_system if file_system is not None else FileSystem(base_dir='./')
		self.available_file_paths = available_file_paths or []
		self.sensitive_data = sensitive_data
		self.max_steps = max_steps
		self.use_vision = use_vision

		self.session = NotebookSession()
		self.namespace: dict[str, Any] = {}
		self._llm_messages: list[BaseMessage] = []  # Internal LLM conversation history
		self.complete_history: list[dict] = []  # Eval system history with model_output and result
		self.dom_service: DomService | None = None
		self._last_browser_state_text: str | None = None  # Track last browser state text
		self._last_screenshot: str | None = None  # Track last screenshot (base64)
		self._consecutive_errors = 0  # Track consecutive errors for auto-termination
		self._max_consecutive_errors = 5  # Maximum consecutive errors before termination
		self._last_llm_usage: Any | None = None  # Track last LLM call usage stats
		self._step_start_time: float = 0.0  # Track step start time for duration calculation
		self.usage_summary = None  # Track usage summary across run for history property

		# Initialize screenshot service for eval tracking
		self.id = uuid7str()
		timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
		base_tmp = Path('/tmp')
		self.agent_directory = base_tmp / f'browser_use_code_agent_{self.id}_{timestamp}'
		self.screenshot_service = ScreenshotService(agent_directory=self.agent_directory)

		# Initialize token cost service for usage tracking
		self.token_cost_service = TokenCost(include_cost=calculate_cost)
		self.token_cost_service.register_llm(llm)
		if page_extraction_llm:
			self.token_cost_service.register_llm(page_extraction_llm)

	async def run(self, max_steps: int | None = None) -> NotebookSession:
		"""
		Run the agent to complete the task.

		Args:
			max_steps: Optional override for maximum number of steps (uses __init__ value if not provided)

		Returns:
			The notebook session with all executed cells
		"""
		# Use override if provided, otherwise use value from __init__
		steps_to_run = max_steps if max_steps is not None else self.max_steps
		self.max_steps = steps_to_run
		# Start browser if not provided
		if self.browser_session is None:
			self.browser_session = BrowserSession(browser_profile=self.browser_profile)
			await self.browser_session.start()

		# Initialize DOM service with cross-origin iframe support enabled
		self.dom_service = DomService(
			browser_session=self.browser_session,
			cross_origin_iframes=True,  # Enable for code-use agent to access forms in iframes
		)

		# Create namespace with all tools
		self.namespace = create_namespace(
			browser_session=self.browser_session,
			tools=self.tools,
			page_extraction_llm=self.page_extraction_llm,
			file_system=self.file_system,
			available_file_paths=self.available_file_paths,
			sensitive_data=self.sensitive_data,
		)

		# Load system prompt
		system_prompt_path = Path(__file__).parent / 'system_prompt.md'
		system_prompt = system_prompt_path.read_text()

		# Initialize conversation with task
		self._llm_messages.append(SystemMessage(content=system_prompt))
		self._llm_messages.append(UserMessage(content=f'Task: {self.task}'))

		# Extract URL from task and navigate if found
		initial_url = self._extract_url_from_task(self.task)
		if initial_url:
			try:
				logger.info(f'Extracted URL from task, navigating to: {initial_url}')
				# Use the navigate action from namespace
				await self.namespace['navigate'](initial_url)
				# Wait for page load
				await asyncio.sleep(2)

				# Record this navigation as a cell in the notebook
				nav_code = f"await navigate('{initial_url}')"
				cell = self.session.add_cell(source=nav_code)
				cell.status = ExecutionStatus.SUCCESS
				cell.execution_count = self.session.increment_execution_count()
				cell.output = f'Navigated to {initial_url}'

				# Get browser state after navigation for the cell
				if self.dom_service:
					try:
						browser_state_text, _ = await self._get_browser_state()
						cell.browser_state = browser_state_text
					except Exception as state_error:
						logger.debug(f'Failed to capture browser state for initial navigation cell: {state_error}')

			except Exception as e:
				logger.warning(f'Failed to navigate to extracted URL {initial_url}: {e}')
				# Record failed navigation as error cell
				nav_code = f"await navigate('{initial_url}')"
				cell = self.session.add_cell(source=nav_code)
				cell.status = ExecutionStatus.ERROR
				cell.execution_count = self.session.increment_execution_count()
				cell.error = str(e)

		# Get initial browser state before first LLM call
		if self.browser_session and self.dom_service:
			try:
				browser_state_text, screenshot = await self._get_browser_state()
				self._last_browser_state_text = browser_state_text
				self._last_screenshot = screenshot
			except Exception as e:
				logger.warning(f'Failed to get initial browser state: {e}')

		# Main execution loop
		for step in range(self.max_steps):
			logger.info(f'\n\n\n\n\n\n\nStep {step + 1}/{self.max_steps}')

			# Start timing this step
			self._step_start_time = datetime.datetime.now().timestamp()

			# Check if we're approaching the step limit or error limit and inject warning
			steps_remaining = self.max_steps - step - 1
			errors_remaining = self._max_consecutive_errors - self._consecutive_errors

			should_warn = (
				steps_remaining <= 1  # Last step or next to last
				or errors_remaining <= 1  # One more error will terminate
				or (steps_remaining <= 2 and self._consecutive_errors >= 2)  # Close to both limits
			)

			if should_warn:
				warning_message = (
					f'\n\n⚠️ CRITICAL WARNING: You are approaching execution limits!\n'
					f'- Steps remaining: {steps_remaining + 1}\n'
					f'- Consecutive errors: {self._consecutive_errors}/{self._max_consecutive_errors}\n\n'
					f'YOU MUST call done() in your NEXT response, even if the task is incomplete:\n'
					f"- Set success=False if you couldn't complete the task\n"
					f'- Return EVERYTHING you found so far (partial data is better than nothing)\n'
					f"- Include any variables you've stored (products, all_data, etc.)\n"
					f"- Explain what worked and what didn't\n\n"
					f'Without done(), the user will receive NOTHING.'
				)
				self._llm_messages.append(UserMessage(content=warning_message))

			try:
				# Get code from LLM (this also adds to self._llm_messages)
				try:
					code, full_llm_response = await self._get_code_from_llm()
				except Exception as llm_error:
					# LLM call failed - count as consecutive error and retry
					self._consecutive_errors += 1
					logger.warning(
						f'LLM call failed (consecutive errors: {self._consecutive_errors}/{self._max_consecutive_errors}), retrying: {llm_error}'
					)

					# Check if we've hit the consecutive error limit
					if self._consecutive_errors >= self._max_consecutive_errors:
						logger.error(f'Terminating: {self._max_consecutive_errors} consecutive LLM failures')
						break

					await asyncio.sleep(1)  # Brief pause before retry
					continue

				if not code or code.strip() == '':
					logger.warning('LLM returned empty code')
					self._consecutive_errors += 1

					# new state
					if self.browser_session and self.dom_service:
						try:
							browser_state_text, screenshot = await self._get_browser_state()
							self._last_browser_state_text = browser_state_text
							self._last_screenshot = screenshot
						except Exception as e:
							logger.warning(f'Failed to get new browser state: {e}')
					continue

				# Execute code blocks sequentially if multiple python blocks exist
				# This allows JS/bash blocks to be injected into namespace before Python code uses them
				all_blocks = self.namespace.get('_all_code_blocks', {})
				python_blocks = [k for k in sorted(all_blocks.keys()) if k.startswith('python_')]

				if len(python_blocks) > 1:
					# Multiple Python blocks - execute each sequentially
					output = None
					error = None
					browser_state = None

					for i, block_key in enumerate(python_blocks):
						logger.info(f'Executing Python block {i+1}/{len(python_blocks)}')
						block_code = all_blocks[block_key]
						block_output, block_error, block_browser_state = await self._execute_code(block_code)

						# Accumulate outputs
						if block_output:
							output = (output or '') + block_output
						if block_error:
							error = block_error
							# Stop on first error
							break
						# Keep last browser state
						if block_browser_state:
							browser_state = block_browser_state
				else:
					# Single Python block - execute normally
					output, error, browser_state = await self._execute_code(code)

				# Track consecutive errors
				if error:
					self._consecutive_errors += 1
					logger.warning(f'Consecutive errors: {self._consecutive_errors}/{self._max_consecutive_errors}')

					# Check if we've hit the consecutive error limit
					if self._consecutive_errors >= self._max_consecutive_errors:
						logger.error(
							f'Terminating: {self._max_consecutive_errors} consecutive errors reached. '
							f'The agent is unable to make progress.'
						)
						# Add termination message to complete history before breaking
						await self._add_step_to_complete_history(
							model_output_code=code,
							full_llm_response=f'[Terminated after {self._max_consecutive_errors} consecutive errors]',
							output=None,
							error=f'Auto-terminated: {self._max_consecutive_errors} consecutive errors without progress',
							screenshot_path=None,
						)
						break
				else:
					# Reset consecutive error counter on success
					self._consecutive_errors = 0

				# Check if task is done - validate completion first if not at limits
				if self._is_task_done():
					# Get the final result from namespace (from done() call)
					final_result = self.namespace.get('_task_result')

					# Check if we should validate (not at step/error limits)
					steps_remaining = self.max_steps - step - 1
					should_validate = (
						steps_remaining >= 4  # At least 4 steps away from limit
						and self._consecutive_errors < 3  # Not close to error limit (5 consecutive)
					)

					if should_validate:
						logger.info('Validating task completion with LLM...')
						from .namespace import validate_task_completion

						is_complete, reasoning = await validate_task_completion(
							task=self.task,
							output=final_result,
							llm=self.llm,
						)

						if not is_complete:
							# Task not truly complete - inject feedback and continue
							logger.warning('Validator: Task not complete, continuing...')
							validation_feedback = (
								f'\n\n⚠️ VALIDATOR FEEDBACK:\n'
								f'Your done() call was rejected. The task is NOT complete yet.\n\n'
								f'Validation reasoning:\n{reasoning}\n\n'
								f'You must continue working on the task. Analyze what is missing and complete it.\n'
								f'Do NOT call done() again until the task is truly finished.'
							)

							# Clear the done flag so execution continues
							self.namespace['_task_done'] = False
							self.namespace.pop('_task_result', None)
							self.namespace.pop('_task_success', None)

							# Add validation feedback to LLM messages
							self._llm_messages.append(UserMessage(content=validation_feedback))

							# Don't override output - let execution continue normally
						else:
							logger.info('Validator: Task complete')
							# Override output with done message for final step
							if final_result:
								output = final_result
					else:
						# At limits - skip validation and accept done()
						logger.info('At step/error limits - skipping validation')
						if final_result:
							output = final_result

				if output:
					# Check if this is the final done() output
					if self._is_task_done():
						# Show done() output more prominently
						logger.info(
							f'✓ Task completed - Final output from done():\n{output[:300] if len(output) > 300 else output}'
						)
						# Also show files_to_display if they exist in namespace
						attachments = self.namespace.get('_task_attachments')
						if attachments:
							logger.info(f'Files displayed: {", ".join(attachments)}')
					else:
						logger.info(f'Code output:\n{output}')
				if browser_state:
					# Cap browser state logging to 1000 chars
					if len(browser_state) > 2000:
						logger.info(
							f'Browser state:\n{browser_state[:2000]}...\n[Truncated, full state sent to LLM {len(browser_state)} chars]'
						)
					else:
						logger.info(f'Browser state:\n{browser_state}')

				# Take screenshot for eval tracking
				screenshot_path = await self._capture_screenshot(step + 1)

				# Add step to complete_history for eval system
				await self._add_step_to_complete_history(
					model_output_code=code,
					full_llm_response=full_llm_response,
					output=output,
					error=error,
					screenshot_path=screenshot_path,
				)

				# Check if task is done (after validation)
				if self._is_task_done():
					# Get the final result from namespace
					final_result = self.namespace.get('_task_result', output)
					logger.info('Task completed successfully')
					if final_result:
						logger.info(f'Final result: {final_result}')
					break
				# If validation rejected done(), continue to next iteration
				# The feedback message has already been added to _llm_messages

				# Add result to LLM messages for next iteration (without browser state)
				result_message = self._format_execution_result(code, output, error, current_step=step + 1)
				truncated_result = _truncate_message_content(result_message)
				self._llm_messages.append(UserMessage(content=truncated_result))

			except Exception as e:
				logger.error(f'Error in step {step + 1}: {e}')
				traceback.print_exc()
				break
		else:
			# Loop completed without break - max_steps reached
			logger.warning(f'Maximum steps ({self.max_steps}) reached without task completion')

		# If task is not done, capture the last step's output as partial result
		if not self._is_task_done() and self.complete_history:
			# Get the last step's output/error and use it as final extracted_content
			last_step = self.complete_history[-1]
			last_result = last_step['result'][0] if last_step.get('result') else {}
			last_output = last_result.get('extracted_content')
			last_error = last_result.get('error')

			# Build a partial result message from the last step
			partial_result_parts = []
			partial_result_parts.append(f'Task incomplete - reached step limit ({self.max_steps} steps).')
			partial_result_parts.append('Last step output:')

			if last_output:
				partial_result_parts.append(f'\nOutput: {last_output}')
			if last_error:
				partial_result_parts.append(f'\nError: {last_error}')

			# Add any accumulated variables that might contain useful data
			data_vars = []
			for var_name in sorted(self.namespace.keys()):
				if not var_name.startswith('_') and var_name not in {'json', 'asyncio', 'csv', 're', 'datetime', 'Path'}:
					var_value = self.namespace[var_name]
					# Check if it's a list or dict that might contain collected data
					if isinstance(var_value, (list, dict)) and var_value:
						data_vars.append(f'  - {var_name}: {type(var_value).__name__} with {len(var_value)} items')

			if data_vars:
				partial_result_parts.append('\nVariables in namespace that may contain partial data:')
				partial_result_parts.extend(data_vars)

			partial_result = '\n'.join(partial_result_parts)

			# Update the last step's extracted_content with this partial result
			last_step['result'][0]['extracted_content'] = partial_result
			last_step['result'][0]['is_done'] = False
			last_step['result'][0]['success'] = False

			logger.info(f'\nPartial result captured from last step:\n{partial_result}')

		# Log final summary if task was completed
		if self._is_task_done():
			logger.info('\n' + '=' * 60)
			logger.info('TASK COMPLETED SUCCESSFULLY')
			logger.info('=' * 60)
			final_result = self.namespace.get('_task_result')
			if final_result:
				logger.info(f'\nFinal Output:\n{final_result}')

			attachments = self.namespace.get('_task_attachments')
			if attachments:
				logger.info(f'\nFiles Attached:\n{chr(10).join(attachments)}')
			logger.info('=' * 60 + '\n')

		# Auto-close browser if keep_alive is False
		await self.close()

		# Store usage summary for history property
		self.usage_summary = await self.token_cost_service.get_usage_summary()

		# Log token usage summary
		await self.token_cost_service.log_usage_summary()

		return self.session

	async def _get_code_from_llm(self) -> tuple[str, str]:
		"""Get Python code from the LLM.

		Returns:
			Tuple of (extracted_code, full_llm_response)
		"""
		# Prepare messages for this request
		# Include browser state as separate message if available (not accumulated in history)
		messages_to_send = self._llm_messages.copy()

		if self._last_browser_state_text:
			# Create message with optional screenshot
			if self.use_vision and self._last_screenshot:
				# Build content with text + screenshot
				content_parts: list[ContentPartTextParam | ContentPartImageParam] = [
					ContentPartTextParam(text=self._last_browser_state_text)
				]

				# Add screenshot
				content_parts.append(
					ContentPartImageParam(
						image_url=ImageURL(
							url=f'data:image/jpeg;base64,{self._last_screenshot}',
							media_type='image/jpeg',
							detail='auto',
						),
					)
				)

				messages_to_send.append(UserMessage(content=content_parts))
			else:
				# Text only
				messages_to_send.append(UserMessage(content=self._last_browser_state_text))

			# Clear browser state after including it so it's only in this request
			self._last_browser_state_text = None
			self._last_screenshot = None

		# Call LLM with message history (including temporary browser state message)
		response = await self.llm.ainvoke(messages_to_send)

		# Store usage stats from this LLM call
		self._last_llm_usage = response.usage

		# Log the LLM's raw output for debugging
		logger.info(f'LLM Response:\n{response.completion}')

		# Store the full response
		full_response = response.completion

		# Extract code blocks from response
		# Support multiple code block types: python, js, bash, markdown
		code_blocks = self._extract_code_blocks(response.completion)

		# Inject non-python blocks into namespace as variables
		# Track which variables are code blocks for browser state display
		if '_code_block_vars' not in self.namespace:
			self.namespace['_code_block_vars'] = set()

		for block_type, block_content in code_blocks.items():
			if not block_type.startswith('python'):
				# Store js, bash, markdown blocks (and named variants) as variables in namespace
				self.namespace[block_type] = block_content
				self.namespace['_code_block_vars'].add(block_type)
				print(f'→ Code block variable: {block_type} (str, {len(block_content)} chars)')
				logger.debug(f'Injected {block_type} block into namespace ({len(block_content)} chars)')

		# Store all code blocks for sequential execution
		self.namespace['_all_code_blocks'] = code_blocks

		# Get Python code (or fallback to raw completion)
		# For backward compatibility, still return 'python' block if it exists
		code = code_blocks.get('python', response.completion)

		# Add to LLM messages (truncate for history to save context)
		truncated_completion = _truncate_message_content(response.completion)
		self._llm_messages.append(AssistantMessage(content=truncated_completion))

		return code, full_response

	def _print_variable_info(self, var_name: str, value: Any) -> None:
		"""Print compact info about a variable assignment."""
		# Skip built-in modules and known imports
		skip_names = {'json', 'asyncio', 'csv', 're', 'datetime', 'Path', 'pd', 'np', 'plt', 'requests', 'BeautifulSoup', 'PdfReader', 'browser', 'file_system'}
		if var_name in skip_names:
			return

		# Skip code block variables (already printed)
		if '_code_block_vars' in self.namespace and var_name in self.namespace.get('_code_block_vars', set()):
			return

		# Print compact variable info
		if isinstance(value, (list, dict)):
			preview = str(value)[:100]
			print(f'→ Variable: {var_name} ({type(value).__name__}, len={len(value)}, preview={preview}...)')
		elif isinstance(value, str) and len(value) > 50:
			print(f'→ Variable: {var_name} (str, {len(value)} chars, preview={value[:50]}...)')
		elif callable(value):
			print(f'→ Variable: {var_name} (function)')
		else:
			print(f'→ Variable: {var_name} ({type(value).__name__}, value={repr(value)[:50]})')

	def _extract_code_blocks(self, text: str) -> dict[str, str]:
		"""Extract all code blocks from markdown response.

		Supports:
		- ```python, ```js, ```javascript, ```bash, ```markdown, ```md
		- Named blocks: ```js variable_name → saved as 'variable_name' in namespace

		Returns dict mapping block_name -> content

		Note: Python blocks are NO LONGER COMBINED. Each python block executes separately
		to allow sequential execution with JS/bash blocks in between.
		"""
		import re

		# Pattern to match code blocks with language identifier and optional variable name
		# Matches: ```lang\n or ```lang varname\n
		pattern = r'```(\w+)(?:\s+(\w+))?\n(.*?)```'
		matches = re.findall(pattern, text, re.DOTALL)

		blocks: dict[str, str] = {}
		python_block_counter = 0

		for lang, var_name, content in matches:
			lang = lang.lower()

			# Normalize language names
			if lang in ('javascript', 'js'):
				lang_normalized = 'js'
			elif lang in ('markdown', 'md'):
				lang_normalized = 'markdown'
			elif lang in ('sh', 'shell'):
				lang_normalized = 'bash'
			elif lang == 'python':
				lang_normalized = 'python'
			else:
				# Unknown language, skip
				continue

			# Only process supported types
			if lang_normalized in ('python', 'js', 'bash', 'markdown'):
				content = content.rstrip()  # Only strip trailing whitespace, preserve leading for indentation
				if content:
					# Determine the key to use
					if var_name:
						# Named block - use the variable name
						block_key = var_name
						blocks[block_key] = content
					elif lang_normalized == 'python':
						# Unnamed Python blocks - give each a unique key to preserve order
						block_key = f'python_{python_block_counter}'
						blocks[block_key] = content
						python_block_counter += 1
					else:
						# Other unnamed blocks (js, bash, markdown) - keep last one only
						blocks[lang_normalized] = content

		# If we have multiple python blocks, mark the first one as 'python' for backward compat
		if python_block_counter > 0:
			blocks['python'] = blocks['python_0']

		# Fallback: if no python block but there's generic ``` block, treat as python
		if python_block_counter == 0 and 'python' not in blocks:
			generic_pattern = r'```\n(.*?)```'
			generic_matches = re.findall(generic_pattern, text, re.DOTALL)
			if generic_matches:
				combined = '\n\n'.join(m.strip() for m in generic_matches if m.strip())
				if combined:
					blocks['python'] = combined

		return blocks

	async def _execute_code(self, code: str) -> tuple[str | None, str | None, str | None]:
		"""
		Execute Python code in the namespace.

		Args:
			code: The Python code to execute

		Returns:
			Tuple of (output, error, browser_state)
		"""
		# Create new cell
		cell = self.session.add_cell(source=code)
		cell.status = ExecutionStatus.RUNNING
		cell.execution_count = self.session.increment_execution_count()

		output = None
		error = None
		browser_state = None

		try:
			# Capture output
			import ast
			import io
			import sys

			old_stdout = sys.stdout
			sys.stdout = io.StringIO()

			try:
				# Add asyncio to namespace if not already there
				if 'asyncio' not in self.namespace:
					self.namespace['asyncio'] = asyncio

				# Store the current code in namespace for done() validation
				self.namespace['_current_cell_code'] = code
				# Store consecutive errors count for done() validation
				self.namespace['_consecutive_errors'] = self._consecutive_errors

				# Check if code contains await expressions - if so, wrap in async function
				# This mimics how Jupyter/IPython handles top-level await
				try:
					tree = ast.parse(code, mode='exec')
					has_await = any(isinstance(node, (ast.Await, ast.AsyncWith, ast.AsyncFor)) for node in ast.walk(tree))
				except SyntaxError:
					# If parse fails, let exec handle the error
					has_await = False

				if has_await:
					# When code has await, we must wrap in async function
					# To make variables persist naturally (like Jupyter without needing 'global'):
					# 1. Extract all assigned variable names from the code
					# 2. Inject 'global' declarations for variables that already exist in namespace
					# 3. Extract user's explicit global declarations and pre-define those vars
					# 4. Return locals() so we can update namespace with new variables

					# Find all variable names being assigned + user's explicit globals
					try:
						assigned_names = set()
						user_global_names = set()

						for node in ast.walk(tree):
							if isinstance(node, ast.Assign):
								for target in node.targets:
									if isinstance(target, ast.Name):
										assigned_names.add(target.id)
							elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
								assigned_names.add(node.target.id)
							elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
								if hasattr(node, 'target') and isinstance(node.target, ast.Name):
									assigned_names.add(node.target.id)
							elif isinstance(node, ast.Global):
								# Track user's explicit global declarations
								user_global_names.update(node.names)

						# Pre-define any user-declared globals that don't exist yet
						# This prevents NameError when user writes "global foo" before "foo = ..."
						for name in user_global_names:
							if name not in self.namespace:
								self.namespace[name] = None

						# Filter to only existing namespace vars (like Jupyter does)
						# Include both: assigned vars that exist + user's explicit globals
						existing_vars = {name for name in (assigned_names | user_global_names) if name in self.namespace}
					except Exception as e:
						existing_vars = set()

					# Build global declaration if needed
					global_decl = ''
					has_global_decl = False
					if existing_vars:
						vars_str = ', '.join(sorted(existing_vars))
						global_decl = f'    global {vars_str}\n'
						has_global_decl = True

					indented_code = '\n'.join('    ' + line if line.strip() else line for line in code.split('\n'))
					wrapped_code = f"""async def __code_exec__():
{global_decl}{indented_code}
    # Return locals so we can update the namespace
    return locals()

__code_exec_coro__ = __code_exec__()
"""
					# Store whether we added a global declaration (needed for error line mapping)
					self.namespace['_has_global_decl'] = has_global_decl

					# Compile and execute wrapper at module level
					compiled_code = compile(wrapped_code, '<code>', 'exec')
					exec(compiled_code, self.namespace, self.namespace)

					# Get and await the coroutine, then update namespace with new/modified variables
					coro = self.namespace.get('__code_exec_coro__')
					if coro:
						result_locals = await coro
						# Update namespace with all variables from the function's locals
						# This makes variable assignments persist across cells
						if result_locals:
							for key, value in result_locals.items():
								if not key.startswith('_'):
									self.namespace[key] = value
									# Variable info is tracked in "Available" section, no need for verbose inline output

						# Clean up temporary variables
						self.namespace.pop('__code_exec_coro__', None)
						self.namespace.pop('__code_exec__', None)
				else:
					# No await - execute directly at module level for natural variable scoping
					# This means x = x + 10 will work without needing 'global x'

					# Track variables before execution
					vars_before = set(self.namespace.keys())

					compiled_code = compile(code, '<code>', 'exec')
					exec(compiled_code, self.namespace, self.namespace)

					# Track newly created/modified variables (info shown in "Available" section)
					vars_after = set(self.namespace.keys())
					new_vars = vars_after - vars_before

				# Get output
				output_value = sys.stdout.getvalue()
				if output_value:
					output = output_value

			finally:
				sys.stdout = old_stdout

			# Wait 2 seconds for page to stabilize after code execution
			await asyncio.sleep(0.5)

			# Get browser state after execution
			if self.browser_session and self.dom_service:
				try:
					browser_state_text, screenshot = await self._get_browser_state()
					# Store as last browser state for use in next message
					self._last_browser_state_text = browser_state_text
					self._last_screenshot = screenshot
					browser_state = browser_state_text  # For logging and cell storage
				except Exception as e:
					logger.warning(f'Failed to get browser state: {e}')

			cell.status = ExecutionStatus.SUCCESS
			cell.output = output
			cell.browser_state = browser_state

		except Exception as e:
			# Handle EvaluateError specially - JavaScript execution failed
			if isinstance(e, EvaluateError):
				error = str(e)
				cell.status = ExecutionStatus.ERROR
				cell.error = error
				logger.error(f'Code execution error: {error}')

				await asyncio.sleep(1)

				# Get browser state after error
				if self.browser_session and self.dom_service:
					try:
						browser_state_text, screenshot = await self._get_browser_state()
						self._last_browser_state_text = browser_state_text
						self._last_screenshot = screenshot
						browser_state = browser_state_text
					except Exception as browser_state_error:
						logger.warning(f'Failed to get browser state after error: {browser_state_error}')

				# Return immediately - do not continue executing code
				return output, error, browser_state

			# Handle NameError specially - check for code block variable confusion
			if isinstance(e, NameError):
				error_msg = str(e)
				cell.status = ExecutionStatus.ERROR
				cell.error = error

				# Get browser state after error
				await asyncio.sleep(0.5)
				if self.browser_session and self.dom_service:
					try:
						browser_state_text, screenshot = await self._get_browser_state()
						self._last_browser_state_text = browser_state_text
						self._last_screenshot = screenshot
						browser_state = browser_state_text
					except Exception as browser_state_error:
						logger.warning(f'Failed to get browser state after error: {browser_state_error}')

				return output, error, browser_state

			# For syntax errors and common parsing errors, show just the error message
			# without the full traceback to keep output clean
			if isinstance(e, SyntaxError):
				error_msg = e.msg if e.msg else str(e)
				error = f'{type(e).__name__}: {error_msg}'

				# Detect common f-string issues with JSON/JavaScript code
				if 'unterminated' in error_msg.lower() and 'string' in error_msg.lower() and code:
					# Check if code contains f-strings with potential JSON/JS content
					has_fstring = bool(re.search(r'\bf["\']', code))
					has_json_pattern = bool(re.search(r'json\.dumps|"[^"]*\{[^"]*\}[^"]*"|\'[^\']*\{[^\']*\}[^\']*\'', code))
					has_js_pattern = bool(re.search(r'evaluate\(|await evaluate', code))

					if has_fstring and (has_json_pattern or has_js_pattern):
						error += (
							'\n\n💡 TIP: Detected f-string with JSON/JavaScript code containing {}.\n'
							'   Use separate ```js or ```markdown blocks instead of f-strings to avoid escaping issues:\n'
						)

				# Detect and provide helpful hints for common string literal errors
				if 'unterminated' in error_msg.lower() and 'string' in error_msg.lower():
					# Detect what type of string literal is unterminated
					is_triple = 'triple-quoted' in error_msg.lower()
					msg_lower = error_msg.lower()

					# Detect prefix type from error message
					if 'f-string' in msg_lower and 'raw' in msg_lower:
						prefix = 'rf or fr'
						desc = 'raw f-string'
					elif 'f-string' in msg_lower:
						prefix = 'f'
						desc = 'f-string'
					elif 'raw' in msg_lower and 'bytes' in msg_lower:
						prefix = 'rb or br'
						desc = 'raw bytes'
					elif 'raw' in msg_lower:
						prefix = 'r'
						desc = 'raw string'
					elif 'bytes' in msg_lower:
						prefix = 'b'
						desc = 'bytes'
					else:
						prefix = ''
						desc = 'string'

					# Build hint based on triple-quoted vs single/double quoted
					if is_triple:
						if prefix:
							hint = f"Hint: Unterminated {prefix}'''...''' or {prefix}\"\"\"...\"\" ({desc}). Check for missing closing quotes or unescaped quotes inside."
						else:
							hint = "Hint: Unterminated '''...''' or \"\"\"...\"\" detected. Check for missing closing quotes or unescaped quotes inside."
					else:
						if prefix:
							hint = f'Hint: Unterminated {prefix}\'...\' or {prefix}"..." ({desc}). Check for missing closing quote or unescaped quotes inside.'
						else:
							hint = 'Hint: Unterminated \'...\' or "..." detected. Check for missing closing quote or unescaped quotes inside the string.'
					error += f'\n{hint}'

				# Show the problematic line from the code
				if e.text:
					error += f'\n{e.text}'
				elif e.lineno and code:
					# If e.text is empty, extract the line from the code
					lines = code.split('\n')
					if 0 < e.lineno <= len(lines):
						error += f'\n{lines[e.lineno - 1]}'

			else:
				# For other errors, try to extract useful information
				error_str = str(e)
				error = f'{type(e).__name__}: {error_str}' if error_str else f'{type(e).__name__} occurred'

				# For RuntimeError or other exceptions, try to extract traceback info
				# to show which line in the user's code actually failed
				if hasattr(e, '__traceback__'):
					# Walk the traceback to find the frame with '<code>' filename
					tb = e.__traceback__
					user_code_lineno = None
					while tb is not None:
						frame = tb.tb_frame
						if frame.f_code.co_filename == '<code>':
							# Found the frame executing user code
							# Get the line number from the traceback
							user_code_lineno = tb.tb_lineno
							break
						tb = tb.tb_next

			cell.status = ExecutionStatus.ERROR
			cell.error = error
			logger.error(f'Code execution error: {error}')

			await asyncio.sleep(1)

			# Get browser state after error (important for LLM to see state after failure)
			if self.browser_session and self.dom_service:
				try:
					browser_state_text, screenshot = await self._get_browser_state()
					# Store as last browser state for use in next message
					self._last_browser_state_text = browser_state_text
					self._last_screenshot = screenshot
					browser_state = browser_state_text  # For logging and cell storage
				except Exception as browser_state_error:
					logger.warning(f'Failed to get browser state after error: {browser_state_error}')

		return output, error, browser_state

	async def _get_browser_state(self) -> tuple[str, str | None]:
		"""Get the current browser state as text with ultra-minimal DOM structure for code agents.

		Returns:
			Tuple of (browser_state_text, screenshot_base64)
		"""
		if not self.browser_session or not self.dom_service:
			return 'Browser state not available', None

		try:
			# Get full browser state including screenshot if use_vision is enabled
			include_screenshot = True
			state = await self.browser_session.get_browser_state_summary(include_screenshot=include_screenshot)
			assert state.dom_state is not None
			dom_state = state.dom_state

			# Use eval_representation (compact serializer for code agents)
			dom_html = dom_state.eval_representation()
			if dom_html == '':
				dom_html = 'Empty DOM tree (you might have to wait for the page to load)'

			# Format with URL and title header
			lines = ['## Browser State']
			lines.append(f'**URL:** {state.url}')
			lines.append(f'**Title:** {state.title}')
			lines.append('')

			# Add tabs info if multiple tabs exist
			if len(state.tabs) > 1:
				lines.append('**Tabs:**')
				current_target_candidates = []
				# Find tabs that match current URL and title
				for tab in state.tabs:
					if tab.url == state.url and tab.title == state.title:
						current_target_candidates.append(tab.target_id)
				current_target_id = current_target_candidates[0] if len(current_target_candidates) == 1 else None

				for tab in state.tabs:
					is_current = ' (current)' if tab.target_id == current_target_id else ''
					lines.append(f'  - Tab {tab.target_id[-4:]}: {tab.url} - {tab.title[:30]}{is_current}')
				lines.append('')

			# Add page scroll info if available
			if state.page_info:
				pi = state.page_info
				pages_above = pi.pixels_above / pi.viewport_height if pi.viewport_height > 0 else 0
				pages_below = pi.pixels_below / pi.viewport_height if pi.viewport_height > 0 else 0
				total_pages = pi.page_height / pi.viewport_height if pi.viewport_height > 0 else 0

				scroll_info = f'**Page:** {pages_above:.1f} pages above, {pages_below:.1f} pages below'
				if total_pages > 1.2:  # Only mention total if significantly > 1 page
					scroll_info += f', {total_pages:.1f} total pages'
				lines.append(scroll_info)
				lines.append('')

			# Check if jQuery is available on the page
			has_jquery = False
			try:
				cdp_session = await self.browser_session.get_or_create_cdp_session()
				jquery_check = await cdp_session.cdp_client.send.Runtime.evaluate(
					params={
						'expression': '(function(){ return typeof jQuery !== "undefined" && typeof $ !== "undefined"; })()',
						'returnByValue': True,
					},
					session_id=cdp_session.session_id,
				)
				has_jquery = jquery_check.get('result', {}).get('value', False)
			except Exception:
				pass

			# Add available variables and functions BEFORE DOM structure
			# Show useful utilities (json, asyncio, etc.) and user-defined vars, but hide system objects
			skip_vars = {
				'browser',
				'file_system',  # System objects
				'np',
				'pd',
				'plt',
				'numpy',
				'pandas',
				'matplotlib',
				'requests',
				'BeautifulSoup',
				'bs4',
				'pypdf',
				'PdfReader',
				'wait',
			}

			# Highlight code block variables separately from regular variables
			code_block_vars = []
			regular_vars = []
			tracked_code_blocks = self.namespace.get('_code_block_vars', set())
			for name in self.namespace.keys():
				# Skip private vars and system objects/actions
				if not name.startswith('_') and name not in skip_vars:
					if name in tracked_code_blocks:
						code_block_vars.append(name)
					else:
						regular_vars.append(name)

			# Sort for consistent display
			available_vars_sorted = sorted(regular_vars)
			code_block_vars_sorted = sorted(code_block_vars)

			# Add jQuery availability info alongside variables


			# Build available line with code blocks and variables
			parts = []
			if code_block_vars_sorted:
				parts.append(f'**Code block variables:** {", ".join(code_block_vars_sorted)}')
			if available_vars_sorted:
				parts.append(f'**Variables:** {", ".join(available_vars_sorted)}')

			lines.append(f'**Available:** {" | ".join(parts)}')
			lines.append('')

			# Add DOM structure
			lines.append('**DOM Structure:**')

			# Add scroll position hints for DOM
			if state.page_info:
				pi = state.page_info
				pages_above = pi.pixels_above / pi.viewport_height if pi.viewport_height > 0 else 0
				pages_below = pi.pixels_below / pi.viewport_height if pi.viewport_height > 0 else 0

				if pages_above > 0:
					dom_html = f'... {pages_above:.1f} pages above \n{dom_html}'
				else:
					dom_html = '[Start of page]\n' + dom_html

				if pages_below > 0:
					dom_html += f'\n... {pages_below:.1f} pages below '
				else:
					dom_html += '\n[End of page]'

			# Truncate DOM if too long and notify LLM
			max_dom_length = 60000
			if len(dom_html) > max_dom_length:
				lines.append(dom_html[:max_dom_length])
				lines.append(
					f'\n[DOM truncated after {max_dom_length} characters. Full page contains {len(dom_html)} characters total. Use evaluate to explore more.]'
				)
			else:
				lines.append(dom_html)

			browser_state_text = '\n'.join(lines)
			screenshot = state.screenshot if include_screenshot else None

			return browser_state_text, screenshot

		except Exception as e:
			logger.error(f'Failed to get browser state: {e}')
			return f'Error getting browser state: {e}', None

	def _format_execution_result(self, code: str, output: str | None, error: str | None, current_step: int | None = None) -> str:
		"""Format the execution result for the LLM (without browser state)."""
		result = []

		# Add step progress header if step number provided
		if current_step is not None:
			progress_header = f'Step {current_step}/{self.max_steps} executed'
			# Add consecutive failure tracking if there are errors
			if error and self._consecutive_errors > 0:
				progress_header += f' | Consecutive failures: {self._consecutive_errors}/{self._max_consecutive_errors}'
			result.append(progress_header)

		if error:
			result.append(f'Error: {error}')

		if output:
			# Truncate output if too long
			if len(output) > 10000:
				output = output[:9950] + '\n[Truncated after 10000 characters]'
			result.append(f'Output: {output}')
		if len(result) == 0:
			result.append('Executed')
		return '\n'.join(result)

	def _is_task_done(self) -> bool:
		"""Check if the task is marked as done in the namespace."""
		# Check if 'done' was called by looking for a special marker in namespace
		return self.namespace.get('_task_done', False)

	def _extract_url_from_task(self, task: str) -> str | None:
		"""Extract URL from task string using naive pattern matching."""
		import re

		# Remove email addresses from task before looking for URLs
		task_without_emails = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '', task)

		# Look for common URL patterns
		patterns = [
			r'https?://[^\s<>"\']+',  # Full URLs with http/https
			r'(?:www\.)?[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}(?:/[^\s<>"\']*)?',  # Domain names with subdomains and optional paths
		]

		found_urls = []
		for pattern in patterns:
			matches = re.finditer(pattern, task_without_emails)
			for match in matches:
				url = match.group(0)

				# Remove trailing punctuation that's not part of URLs
				url = re.sub(r'[.,;:!?()\[\]]+$', '', url)
				# Add https:// if missing
				if not url.startswith(('http://', 'https://')):
					url = 'https://' + url
				found_urls.append(url)

		unique_urls = list(set(found_urls))
		# If multiple URLs found, skip auto-navigation to avoid ambiguity
		if len(unique_urls) > 1:
			logger.debug(f'Multiple URLs found ({len(found_urls)}), skipping auto-navigation to avoid ambiguity')
			return None

		# If exactly one URL found, return it
		if len(unique_urls) == 1:
			return unique_urls[0]

		return None

	async def _capture_screenshot(self, step_number: int) -> str | None:
		"""Capture and store screenshot for eval tracking."""
		if not self.browser_session:
			return None

		try:
			# Get browser state summary which includes screenshot
			state = await self.browser_session.get_browser_state_summary(include_screenshot=True)
			if state and state.screenshot:
				# Store screenshot using screenshot service
				screenshot_path = await self.screenshot_service.store_screenshot(state.screenshot, step_number)
				return str(screenshot_path) if screenshot_path else None
		except Exception as e:
			logger.warning(f'Failed to capture screenshot for step {step_number}: {e}')
			return None

	async def _add_step_to_complete_history(
		self, model_output_code: str, full_llm_response: str, output: str | None, error: str | None, screenshot_path: str | None
	) -> None:
		"""Add a step to complete_history in eval system format."""
		# Get current browser URL and title for state
		url = None
		title = None
		if self.browser_session:
			try:
				url = await self.browser_session.get_current_page_url()
				# Get title from browser
				cdp_session = await self.browser_session.get_or_create_cdp_session()
				result = await cdp_session.cdp_client.send.Runtime.evaluate(
					params={'expression': 'document.title', 'returnByValue': True},
					session_id=cdp_session.session_id,
				)
				title = result.get('result', {}).get('value')
			except Exception as e:
				logger.debug(f'Failed to get browser URL/title for history: {e}')

		# Create result entry matching eval system expectations
		# Check if this is a done result
		is_done = self._is_task_done()

		# Get self-reported success from done() call if task is done
		self_reported_success = None
		if is_done:
			self_reported_success = self.namespace.get('_task_success')

		result_entry = {
			'extracted_content': output if output else None,
			'error': error if error else None,
			'is_done': is_done,  # Add is_done flag for eval system
			'success': self_reported_success,  # Use self-reported success from done() call
		}

		# Create state entry (will be converted to object with get_screenshot() method by DictToObject)
		# The eval system expects state to have url, title, and get_screenshot() method
		state_entry = {
			'url': url,
			'title': title,
			'screenshot_path': screenshot_path,  # Store path here for get_screenshot() to use
		}

		# Create metadata entry (eval system uses this for token counting and timing)
		step_end_time = datetime.datetime.now().timestamp()
		metadata_entry = {
			'input_tokens': self._last_llm_usage.prompt_tokens if self._last_llm_usage else None,
			'output_tokens': self._last_llm_usage.completion_tokens if self._last_llm_usage else None,
			'step_start_time': self._step_start_time,
			'step_end_time': step_end_time,
		}

		# Create history entry matching eval system format
		# For CodeUseAgent, model_output contains the code and full LLM response
		history_entry = {
			'model_output': {
				'model_output': model_output_code,  # The extracted code
				'full_response': full_llm_response,  # The complete LLM response including any text/reasoning
			},
			'result': [result_entry],  # Always a list
			'state': state_entry,  # Add state entry for eval system
			'metadata': metadata_entry,  # Add metadata for eval system
			'screenshot_path': screenshot_path,  # Keep this for backward compatibility
		}

		self.complete_history.append(history_entry)

	def screenshot_paths(self, n_last: int | None = None) -> list[str | None]:
		"""
		Get screenshot paths from complete_history for eval system.

		Args:
			n_last: Optional number of last screenshots to return

		Returns:
			List of screenshot file paths (or None for missing screenshots)
		"""
		paths = [step.get('screenshot_path') for step in self.complete_history]

		if n_last is not None:
			return paths[-n_last:] if len(paths) > n_last else paths

		return paths

	@property
	def message_manager(self):
		"""
		Compatibility property for eval system.
		Returns a mock object with last_input_messages attribute.
		"""

		class MockMessageManager:
			def __init__(self, llm_messages):
				# Convert code-use LLM messages to format expected by eval system
				self.last_input_messages = llm_messages

		return MockMessageManager(self._llm_messages)

	@property
	def history(self):
		"""
		Compatibility property for eval system.
		Returns a mock AgentHistoryList object with history attribute containing complete_history.
		This is what the eval system expects when it does: agent_history = agent.history
		"""

		class DictToObject:
			"""Convert dict to object with attribute access for eval compatibility."""

			def __init__(self, data):
				for key, value in data.items():
					if isinstance(value, dict):
						setattr(self, key, DictToObject(value))
					elif isinstance(value, list):
						setattr(self, key, [DictToObject(item) if isinstance(item, dict) else item for item in value])
					else:
						setattr(self, key, value)

			def __getattr__(self, name):
				"""Provide safe attribute access with defaults for missing attributes."""
				# Return None for missing attributes instead of raising AttributeError
				# This handles cases where eval system checks attributes that CodeUseAgent doesn't set
				return None

			def model_dump(self):
				"""Support model_dump() calls from eval system."""
				result = {}
				for key, value in self.__dict__.items():
					if isinstance(value, DictToObject):
						result[key] = value.model_dump()
					elif isinstance(value, list):
						result[key] = [item.model_dump() if isinstance(item, DictToObject) else item for item in value]
					else:
						result[key] = value
				return result

			def get_screenshot(self):
				"""Support get_screenshot() calls for state objects."""
				# Load screenshot from disk and return as base64 string (matching BrowserStateHistory implementation)
				if not hasattr(self, 'screenshot_path') or not self.screenshot_path:
					return None

				import base64
				from pathlib import Path

				path_obj = Path(self.screenshot_path)
				if not path_obj.exists():
					return None

				try:
					with open(path_obj, 'rb') as f:
						screenshot_data = f.read()
					return base64.b64encode(screenshot_data).decode('utf-8')
				except Exception:
					return None

		class MockAgentHistoryList:
			def __init__(self, complete_history, usage_summary):
				# Convert each dict in complete_history to objects with attribute access
				self.history = [DictToObject(item) for item in complete_history]
				# Use the provided usage summary
				self.usage = usage_summary

		return MockAgentHistoryList(self.complete_history, self.usage_summary)

	async def close(self):
		"""Close the browser session."""
		if self.browser_session:
			# Check if we should close the browser based on keep_alive setting
			if not self.browser_session.browser_profile.keep_alive:
				await self.browser_session.kill()
			else:
				logger.debug('Browser keep_alive is True, not closing browser session')

	async def __aenter__(self):
		"""Async context manager entry."""
		return self

	async def __aexit__(self, exc_type, exc_val, exc_tb):
		"""Async context manager exit."""
		await self.close()
