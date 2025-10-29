"""Code-use agent service - Jupyter notebook-like code execution for browser automation."""

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
	UserMessage,
)
from browser_use.screenshots.service import ScreenshotService
from browser_use.telemetry.service import ProductTelemetry
from browser_use.telemetry.views import AgentTelemetryEvent
from browser_use.tokens.service import TokenCost
from browser_use.tokens.views import UsageSummary
from browser_use.tools.service import Tools
from browser_use.utils import get_browser_use_version

from .formatting import format_browser_state_for_llm
from .namespace import EvaluateError, create_namespace
from .utils import detect_token_limit_issue, extract_code_blocks, extract_url_from_task, truncate_message_content
from .views import (
	CodeAgentHistory,
	CodeAgentModelOutput,
	CodeAgentResult,
	CodeAgentState,
	CodeAgentStepMetadata,
	ExecutionStatus,
	NotebookSession,
)

logger = logging.getLogger(__name__)


class CodeAgent:
	"""
	Agent that executes Python code in a notebook-like environment for browser automation.

	This agent provides a Jupyter notebook-like interface where the LLM writes Python code
	that gets executed in a persistent namespace with browser control functions available.
	"""

	def __init__(
		self,
		task: str,
		# Optional parameters
		llm: BaseChatModel | None = None,
		browser_session: BrowserSession | None = None,
		browser: BrowserSession | None = None,  # Alias for browser_session
		tools: Tools | None = None,
		controller: Tools | None = None,  # Alias for tools
		# Agent settings
		page_extraction_llm: BaseChatModel | None = None,
		file_system: FileSystem | None = None,
		available_file_paths: list[str] | None = None,
		sensitive_data: dict[str, str | dict[str, str]] | None = None,
		max_steps: int = 100,
		max_failures: int = 8,
		max_validations: int = 0,
		use_vision: bool = True,
		calculate_cost: bool = False,
		**kwargs,
	):
		"""
		Initialize the code-use agent.

		Args:
			task: The task description for the agent
			browser_session: Optional browser session (will be created if not provided) [DEPRECATED: use browser]
			browser: Optional browser session (cleaner API)
			tools: Optional Tools instance (will create default if not provided)
			controller: Optional Tools instance
			page_extraction_llm: Optional LLM for page extraction
			file_system: Optional file system for file operations
			available_file_paths: Optional list of available file paths
			sensitive_data: Optional sensitive data dictionary
			max_steps: Maximum number of execution steps
			max_failures: Maximum consecutive errors before termination (default: 8)
			max_validations: Maximum number of times to run the validator agent (default: 0)
			use_vision: Whether to include screenshots in LLM messages (default: True)
			calculate_cost: Whether to calculate token costs (default: False)
			llm: Optional ChatBrowserUse LLM instance (will create default if not provided)
			**kwargs: Additional keyword arguments for compatibility (ignored)
		"""
		# Log and ignore unknown kwargs for compatibility
		if kwargs:
			logger.debug(f'Ignoring additional kwargs for CodeAgent compatibility: {list(kwargs.keys())}')

		if llm is None:
			try:
				from browser_use import ChatBrowserUse

				llm = ChatBrowserUse()
				logger.debug('CodeAgent using ChatBrowserUse')
			except Exception as e:
				raise RuntimeError(f'Failed to initialize CodeAgent LLM: {e}')

		if 'ChatBrowserUse' not in llm.__class__.__name__:
			raise ValueError('This agent works only with ChatBrowserUse.')

		# Handle browser vs browser_session parameter (browser takes precedence)
		if browser and browser_session:
			raise ValueError('Cannot specify both "browser" and "browser_session" parameters. Use "browser" for the cleaner API.')
		browser_session = browser or browser_session

		# Handle controller vs tools parameter (controller takes precedence)
		if controller and tools:
			raise ValueError('Cannot specify both "controller" and "tools" parameters. Use "controller" for the cleaner API.')
		tools = controller or tools

		# Store browser_profile for creating browser session if needed
		self._browser_profile_for_init = BrowserProfile() if browser_session is None else None

		self.task = task
		self.llm = llm
		self.browser_session = browser_session
		self.tools = tools or Tools()
		self.page_extraction_llm = page_extraction_llm
		self.file_system = file_system if file_system is not None else FileSystem(base_dir='./')
		self.available_file_paths = available_file_paths or []
		self.sensitive_data = sensitive_data
		self.max_steps = max_steps
		self.max_failures = max_failures
		self.max_validations = max_validations
		self.use_vision = use_vision

		self.session = NotebookSession()
		self.namespace: dict[str, Any] = {}
		self._llm_messages: list[BaseMessage] = []  # Internal LLM conversation history
		self.complete_history: list[CodeAgentHistory] = []  # Type-safe history with model_output and result
		self.dom_service: DomService | None = None
		self._last_browser_state_text: str | None = None  # Track last browser state text
		self._last_screenshot: str | None = None  # Track last screenshot (base64)
		self._consecutive_errors = 0  # Track consecutive errors for auto-termination
		self._validation_count = 0  # Track number of validator runs
		self._last_llm_usage: Any | None = None  # Track last LLM call usage stats
		self._step_start_time = 0.0  # Track step start time for duration calculation
		self.usage_summary: UsageSummary | None = None  # Track usage summary across run for history property

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

		# Set version and source for telemetry
		self.version = get_browser_use_version()
		try:
			package_root = Path(__file__).parent.parent.parent
			repo_files = ['.git', 'README.md', 'docs', 'examples']
			if all(Path(package_root / file).exists() for file in repo_files):
				self.source = 'git'
			else:
				self.source = 'pip'
		except Exception:
			self.source = 'unknown'

		# Telemetry
		self.telemetry = ProductTelemetry()

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
			assert self._browser_profile_for_init is not None
			self.browser_session = BrowserSession(browser_profile=self._browser_profile_for_init)
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

		# Initialize conversation with task
		self._llm_messages.append(UserMessage(content=f'Task: {self.task}'))

		# Track agent run error for telemetry
		agent_run_error: str | None = None

		# Extract URL from task and navigate if found
		initial_url = extract_url_from_task(self.task)
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
			errors_remaining = self.max_failures - self._consecutive_errors

			should_warn = (
				steps_remaining <= 1  # Last step or next to last
				or errors_remaining <= 1  # One more error will terminate
				or (steps_remaining <= 2 and self._consecutive_errors >= 2)  # Close to both limits
			)

			if should_warn:
				warning_message = (
					f'\n\n⚠️ CRITICAL WARNING: You are approaching execution limits!\n'
					f'- Steps remaining: {steps_remaining + 1}\n'
					f'- Consecutive errors: {self._consecutive_errors}/{self.max_failures}\n\n'
					f'YOU MUST call done() in your NEXT response, even if the task is incomplete:\n'
					f"- Set success=False if you couldn't complete the task\n"
					f'- Return EVERYTHING you found so far (partial data is better than nothing)\n'
					f"- Include any variables you've stored (products, all_data, etc.)\n"
					f"- Explain what worked and what didn't\n\n"
					f'Without done(), the user will receive NOTHING.'
				)
				self._llm_messages.append(UserMessage(content=warning_message))

			try:
				# Fetch fresh browser state right before LLM call (only if not already set)
				if not self._last_browser_state_text and self.browser_session and self.dom_service:
					try:
						logger.debug('🔍 Fetching browser state before LLM call...')
						browser_state_text, screenshot = await self._get_browser_state()
						self._last_browser_state_text = browser_state_text
						self._last_screenshot = screenshot

						# # Log browser state
						# if len(browser_state_text) > 2000:
						# 	logger.info(
						# 		f'Browser state (before LLM):\n{browser_state_text[:2000]}...\n[Truncated, full state {len(browser_state_text)} chars sent to LLM]'
						# 	)
						# else:
						# 	logger.info(f'Browser state (before LLM):\n{browser_state_text}')
					except Exception as e:
						logger.warning(f'Failed to get browser state before LLM call: {e}')

				# Get code from LLM (this also adds to self._llm_messages)
				try:
					code, full_llm_response = await self._get_code_from_llm()
				except Exception as llm_error:
					# LLM call failed - count as consecutive error and retry
					self._consecutive_errors += 1
					logger.warning(
						f'LLM call failed (consecutive errors: {self._consecutive_errors}/{self.max_failures}), retrying: {llm_error}'
					)

					# Check if we've hit the consecutive error limit
					if self._consecutive_errors >= self.max_failures:
						logger.error(f'Terminating: {self.max_failures} consecutive LLM failures')
						break

					await asyncio.sleep(1)  # Brief pause before retry
					continue

				if not code or code.strip() == '':
					# If task is already done, empty code is fine (LLM explaining completion)
					if self._is_task_done():
						logger.info('Task already marked as done, LLM provided explanation without code')
						# Add the text response to history as a non-code step
						await self._add_step_to_complete_history(
							model_output_code='',
							full_llm_response=full_llm_response,
							output=full_llm_response,  # Treat the explanation as output
							error=None,
							screenshot_path=await self._capture_screenshot(step + 1),
						)
						break  # Exit the loop since task is done

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

					for i, block_key in enumerate(python_blocks):
						logger.info(f'Executing Python block {i + 1}/{len(python_blocks)}')
						block_code = all_blocks[block_key]
						block_output, block_error, _ = await self._execute_code(block_code)

						# Accumulate outputs
						if block_output:
							output = (output or '') + block_output
						if block_error:
							error = block_error
							# Stop on first error
							break
				else:
					# Single Python block - execute normally
					output, error, _ = await self._execute_code(code)

				# Track consecutive errors
				if error:
					self._consecutive_errors += 1
					logger.warning(f'Consecutive errors: {self._consecutive_errors}/{self.max_failures}')

					# Check if we've hit the consecutive error limit
					if self._consecutive_errors >= self.max_failures:
						logger.error(
							f'Terminating: {self.max_failures} consecutive errors reached. The agent is unable to make progress.'
						)
						# Add termination message to complete history before breaking
						await self._add_step_to_complete_history(
							model_output_code=code,
							full_llm_response=f'[Terminated after {self.max_failures} consecutive errors]',
							output=None,
							error=f'Auto-terminated: {self.max_failures} consecutive errors without progress',
							screenshot_path=None,
						)
						break
				else:
					# Reset consecutive error counter on success
					self._consecutive_errors = 0

				# Check if task is done - validate completion first if not at limits
				if self._is_task_done():
					# Get the final result from namespace (from done() call)
					final_result: str | None = self.namespace.get('_task_result')  # type: ignore[assignment]

					# Check if we should validate (not at step/error limits and under max validations)
					steps_remaining = self.max_steps - step - 1
					should_validate = (
						self._validation_count < self.max_validations  # Haven't exceeded max validations
						and steps_remaining >= 4  # At least 4 steps away from limit
						and self._consecutive_errors < 3  # Not close to error limit (8 consecutive)
					)

					if should_validate:
						self._validation_count += 1
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
						if self._validation_count >= self.max_validations:
							logger.info(
								f'Reached max validations ({self.max_validations}) - skipping validation and accepting done()'
							)
						else:
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
						attachments: list[str] | None = self.namespace.get('_task_attachments')  # type: ignore[assignment]
						if attachments:
							logger.info(f'Files displayed: {", ".join(attachments)}')
					else:
						logger.info(f'Code output:\n{output}')

				# Browser state is now only logged when fetched before LLM call (not after execution)

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
					final_result: str | None = self.namespace.get('_task_result', output)  # type: ignore[assignment]
					logger.info('Task completed successfully')
					if final_result:
						logger.info(f'Final result: {final_result}')
					break
				# If validation rejected done(), continue to next iteration
				# The feedback message has already been added to _llm_messages

				# Add result to LLM messages for next iteration (without browser state)
				result_message = self._format_execution_result(code, output, error, current_step=step + 1)
				truncated_result = truncate_message_content(result_message)
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
			last_result = last_step.result[0] if last_step.result else None
			last_output = last_result.extracted_content if last_result else None
			last_error = last_result.error if last_result else None

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
			if last_result:
				last_result.extracted_content = partial_result
				last_result.is_done = False
				last_result.success = False

			logger.info(f'\nPartial result captured from last step:\n{partial_result}')

		# Log final summary if task was completed
		if self._is_task_done():
			logger.info('\n' + '=' * 60)
			logger.info('TASK COMPLETED SUCCESSFULLY')
			logger.info('=' * 60)
			final_result: str | None = self.namespace.get('_task_result')  # type: ignore[assignment]
			if final_result:
				logger.info(f'\nFinal Output:\n{final_result}')

			attachments: list[str] | None = self.namespace.get('_task_attachments')  # type: ignore[assignment]
			if attachments:
				logger.info(f'\nFiles Attached:\n{chr(10).join(attachments)}')
			logger.info('=' * 60 + '\n')

		# Auto-close browser if keep_alive is False
		await self.close()

		# Store usage summary for history property
		self.usage_summary = await self.token_cost_service.get_usage_summary()

		# Log token usage summary
		await self.token_cost_service.log_usage_summary()

		# Log telemetry event
		try:
			self._log_agent_event(max_steps=self.max_steps, agent_run_error=agent_run_error)
		except Exception as log_e:
			logger.error(f'Failed to log telemetry event: {log_e}', exc_info=True)

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

		# Check for token limit or repetition issues
		max_tokens = getattr(self.llm, 'max_tokens', None)
		completion_tokens = response.usage.completion_tokens if response.usage else None
		is_problematic, issue_message = detect_token_limit_issue(
			completion=response.completion,
			completion_tokens=completion_tokens,
			max_tokens=max_tokens,
			stop_reason=response.stop_reason,
		)

		if is_problematic:
			logger.warning(f'Token limit issue detected: {issue_message}')
			# Don't add the bad response to history
			# Instead, inject a system message prompting recovery
			recovery_prompt = (
				f'Your previous response hit a token limit or became repetitive: {issue_message}\n\n'
				'Please write a SHORT plan (2 sentences) for what to do next, then execute ONE simple action.'
			)
			self._llm_messages.append(UserMessage(content=recovery_prompt))
			# Return a controlled error message instead of corrupted code
			return '', f'[Token limit error: {issue_message}]'

		# Store the full response
		full_response = response.completion

		# Extract code blocks from response
		# Support multiple code block types: python, js, bash, markdown
		code_blocks = extract_code_blocks(response.completion)

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

		# Get Python code if it exists
		# If no python block exists and no other code blocks exist, return empty string to skip execution
		# This prevents treating plain text explanations as code
		code = code_blocks.get('python', response.completion)

		# Add to LLM messages (truncate for history to save context)
		truncated_completion = truncate_message_content(response.completion)
		self._llm_messages.append(AssistantMessage(content=truncated_completion))

		return code, full_response

	def _print_variable_info(self, var_name: str, value: Any) -> None:
		"""Print compact info about a variable assignment."""
		# Skip built-in modules and known imports
		skip_names = {
			'json',
			'asyncio',
			'csv',
			're',
			'datetime',
			'Path',
			'pd',
			'np',
			'plt',
			'requests',
			'BeautifulSoup',
			'PdfReader',
			'browser',
			'file_system',
		}
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

			# Note: Browser state is now fetched right before LLM call instead of after each execution
			# This reduces unnecessary state fetches for operations that don't affect the browser

			cell.status = ExecutionStatus.SUCCESS
			cell.output = output
			cell.browser_state = None  # Will be captured in next iteration before LLM call

		except Exception as e:
			# Handle EvaluateError specially - JavaScript execution failed
			if isinstance(e, EvaluateError):
				error = str(e)
				cell.status = ExecutionStatus.ERROR
				cell.error = error
				logger.error(f'Code execution error: {error}')

				await asyncio.sleep(1)

				# Browser state will be fetched before next LLM call
				# Return immediately - do not continue executing code
				return output, error, None

			# Handle NameError specially - check for code block variable confusion
			if isinstance(e, NameError):
				error_msg = str(e)
				cell.status = ExecutionStatus.ERROR
				cell.error = error

				# Browser state will be fetched before next LLM call
				await asyncio.sleep(0.5)
				return output, error, None

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
							'   Use separate ```js or ```markdown blocks instead of f-strings to avoid escaping issues.\n'
							'   If your code block needs ``` inside it, wrap with 4+ backticks: ````markdown code`\n'
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
						hint += '\n      If you need ``` inside your string, use a ````markdown varname` code block with 4+ backticks instead.'
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

			# Browser state will be fetched before next LLM call

		return output, error, None

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

			# Format browser state with namespace context
			browser_state_text = await format_browser_state_for_llm(
				state=state, namespace=self.namespace, browser_session=self.browser_session
			)

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
				progress_header += f' | Consecutive failures: {self._consecutive_errors}/{self.max_failures}'
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
		self,
		model_output_code: str,
		full_llm_response: str,
		output: str | None,
		error: str | None,
		screenshot_path: str | None,
	) -> None:
		"""Add a step to complete_history using type-safe models."""
		# Get current browser URL and title for state
		url: str | None = None
		title: str | None = None
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

		# Check if this is a done result
		is_done = self._is_task_done()

		# Get self-reported success from done() call if task is done
		self_reported_success: bool | None = None
		if is_done:
			task_success = self.namespace.get('_task_success')
			self_reported_success = task_success if isinstance(task_success, bool) else None

		# Create result entry using typed model
		result_entry = CodeAgentResult(
			extracted_content=output if output else None,
			error=error if error else None,
			is_done=is_done,
			success=self_reported_success,
		)

		# Create state entry using typed model
		state_entry = CodeAgentState(url=url, title=title, screenshot_path=screenshot_path)

		# Create metadata entry using typed model
		step_end_time = datetime.datetime.now().timestamp()
		metadata_entry = CodeAgentStepMetadata(
			input_tokens=self._last_llm_usage.prompt_tokens if self._last_llm_usage else None,
			output_tokens=self._last_llm_usage.completion_tokens if self._last_llm_usage else None,
			step_start_time=self._step_start_time,
			step_end_time=step_end_time,
		)

		# Create model output entry using typed model (if there's code to track)
		model_output_entry: CodeAgentModelOutput | None = None
		if model_output_code or full_llm_response:
			model_output_entry = CodeAgentModelOutput(
				model_output=model_output_code if model_output_code else '',
				full_response=full_llm_response if full_llm_response else '',
			)

		# Create history entry using typed model
		history_entry = CodeAgentHistory(
			model_output=model_output_entry,
			result=[result_entry],
			state=state_entry,
			metadata=metadata_entry,
			screenshot_path=screenshot_path,  # Keep for backward compatibility
		)

		self.complete_history.append(history_entry)

	def _log_agent_event(self, max_steps: int, agent_run_error: str | None = None) -> None:
		"""Send the agent event for this run to telemetry."""
		from urllib.parse import urlparse

		token_summary = self.token_cost_service.get_usage_tokens_for_model(self.llm.model)

		# For CodeAgent, we don't have action history like Agent does
		# Instead we track the code execution cells
		action_history_data: list[list[dict[str, Any]] | None] = []
		for step in self.complete_history:
			# Extract code from model_output if available (type-safe access)
			if step.model_output and step.model_output.full_response:
				code = step.model_output.full_response
				# Represent each code cell as a simple action entry
				action_history_data.append([{'llm_response': code}])
			else:
				action_history_data.append(None)

		# Get final result from the last step or namespace (type-safe)
		final_result: Any = self.namespace.get('_task_result')
		final_result_str: str | None = final_result if isinstance(final_result, str) else None

		# Get URLs visited from complete_history (type-safe access)
		urls_visited: list[str] = []
		for step in self.complete_history:
			if step.state.url and step.state.url not in urls_visited:
				urls_visited.append(step.state.url)

		# Get errors from complete_history (type-safe access)
		errors: list[str] = []
		for step in self.complete_history:
			for result in step.result:
				if result.error:
					errors.append(result.error)

		# Determine success from task completion status (type-safe)
		is_done = self._is_task_done()
		task_success: Any = self.namespace.get('_task_success')
		self_reported_success: bool | None = task_success if isinstance(task_success, bool) else (False if is_done else None)

		self.telemetry.capture(
			AgentTelemetryEvent(
				task=self.task,
				model=self.llm.model,
				model_provider=self.llm.provider,
				max_steps=max_steps,
				max_actions_per_step=1,  # CodeAgent executes one code cell per step
				use_vision=self.use_vision,
				version=self.version,
				source=self.source,
				cdp_url=urlparse(self.browser_session.cdp_url).hostname
				if self.browser_session and self.browser_session.cdp_url
				else None,
				agent_type='code',  # CodeAgent identifier
				action_errors=errors,
				action_history=action_history_data,
				urls_visited=urls_visited,
				steps=len(self.complete_history),
				total_input_tokens=token_summary.prompt_tokens,
				total_output_tokens=token_summary.completion_tokens,
				prompt_cached_tokens=token_summary.prompt_cached_tokens,
				total_tokens=token_summary.total_tokens,
				total_duration_seconds=sum(step.metadata.duration_seconds for step in self.complete_history if step.metadata),
				success=self_reported_success,
				final_result_response=final_result_str,
				error_message=agent_run_error,
			)
		)

	def screenshot_paths(self, n_last: int | None = None) -> list[str | None]:
		"""
		Get screenshot paths from complete_history for eval system.

		Args:
			n_last: Optional number of last screenshots to return

		Returns:
			List of screenshot file paths (or None for missing screenshots)
		"""
		paths = [step.screenshot_path for step in self.complete_history]

		if n_last is not None:
			return paths[-n_last:] if len(paths) > n_last else paths

		return paths

	@property
	def message_manager(self) -> Any:
		"""
		Compatibility property for eval system.
		Returns a mock object with last_input_messages attribute.
		"""

		class MockMessageManager:
			def __init__(self, llm_messages: list[BaseMessage]) -> None:
				# Convert code-use LLM messages to format expected by eval system
				self.last_input_messages = llm_messages

		return MockMessageManager(self._llm_messages)

	@property
	def history(self) -> Any:
		"""
		Compatibility property for eval system.
		Returns a mock AgentHistoryList object with history attribute containing complete_history.
		This is what the eval system expects when it does: agent_history = agent.history
		"""

		class DictToObject:
			"""Convert dict to object with attribute access for eval compatibility."""

			def __init__(self, data: dict[str, Any]) -> None:
				for key, value in data.items():
					if isinstance(value, dict):
						setattr(self, key, DictToObject(value))
					elif isinstance(value, list):
						setattr(self, key, [DictToObject(item) if isinstance(item, dict) else item for item in value])
					else:
						setattr(self, key, value)

			def __getattr__(self, name: str) -> None:
				"""Provide safe attribute access with defaults for missing attributes."""
				# Return None for missing attributes instead of raising AttributeError
				# This handles cases where eval system checks attributes that CodeAgent doesn't set
				return None

			def model_dump(self) -> dict[str, Any]:
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

			def get_screenshot(self) -> str | None:
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
			def __init__(self, complete_history: list[CodeAgentHistory], usage_summary: UsageSummary | None) -> None:
				# Convert each CodeAgentHistory to dict, then to object with attribute access
				self.history = [DictToObject(item.model_dump()) for item in complete_history]
				# Use the provided usage summary
				self.usage = usage_summary

		return MockAgentHistoryList(self.complete_history, self.usage_summary)

	async def close(self) -> None:
		"""Close the browser session."""
		if self.browser_session:
			# Check if we should close the browser based on keep_alive setting
			if not self.browser_session.browser_profile.keep_alive:
				await self.browser_session.kill()
			else:
				logger.debug('Browser keep_alive is True, not closing browser session')

	async def __aenter__(self) -> 'CodeAgent':
		"""Async context manager entry."""
		return self

	async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> None:
		"""Async context manager exit."""
		await self.close()
