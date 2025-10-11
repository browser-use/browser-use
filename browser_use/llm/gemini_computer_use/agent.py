"""Computer Use Agent - Full Mode 2 Implementation

This agent integrates Gemini Computer Use function calls with Browser Use Agent infrastructure.
It executes Computer Use actions via Actor API while maintaining full Browser Use features.
"""

import asyncio
import base64
import json
import logging
from typing import Any

from browser_use.agent.service import Agent
from browser_use.agent.views import ActionResult, AgentOutput
from browser_use.browser.views import BrowserStateSummary
from browser_use.llm.gemini_computer_use.bridge import ComputerUseBridge
from browser_use.llm.gemini_computer_use.chat import ChatGeminiComputerUse


class ComputerUseAgent(Agent):
	"""Agent that uses Gemini Computer Use function calls with Browser Use infrastructure.

	This is Mode 2: Gemini's native Computer Use actions executed via Actor API,
	with full Browser Use Agent features (tools, state management, etc.).
	"""

	def __init__(
		self,
		*args,
		max_function_iterations: int = 20,
		screen_width: int = 1440,
		screen_height: int = 900,
		screenshot_size_threshold: int = 200000,
		screenshot_resize_ratio: float = 0.5,
		**kwargs,
	):
		"""Initialize ComputerUseAgent

		Args:
			max_function_iterations: Maximum number of function calling iterations per step (default: 20)
			screen_width: Browser viewport width for coordinate normalization (default: 1440)
			screen_height: Browser viewport height for coordinate normalization (default: 900)
			screenshot_size_threshold: Max screenshot size in bytes before resizing (default: 200000 = 200KB)
			screenshot_resize_ratio: Ratio to resize screenshots if too large (default: 0.5 = 50%)

		"""
		# Store configuration
		self.max_function_iterations = max_function_iterations
		self.screen_width = screen_width
		self.screen_height = screen_height
		self.screenshot_size_threshold = screenshot_size_threshold
		self.screenshot_resize_ratio = screenshot_resize_ratio

		# Load Computer Use system prompt before calling super().__init__
		computer_use_prompt = self._load_computer_use_system_prompt(kwargs.get('task', 'Complete the task'))

		# Override system message to use Computer Use prompt
		kwargs['override_system_message'] = computer_use_prompt

		super().__init__(*args, **kwargs)

		# Set default output schema if none provided for automatic structured_output support
		if self.output_model_schema is None:
			from pydantic import BaseModel

			class ComputerUseResult(BaseModel):
				result: str

			self.output_model_schema = ComputerUseResult
			# Don't add to tools - just use for structured_output parsing

		# Verify we're using ChatGeminiComputerUse with enable_computer_use=True
		if not isinstance(self.llm, ChatGeminiComputerUse):
			raise ValueError('ComputerUseAgent requires ChatGeminiComputerUse LLM')

		if not self.llm.enable_computer_use:
			self.logger.warning('⚠️  enable_computer_use=False, switching to True for ComputerUseAgent')
			self.llm.enable_computer_use = True

		# Initialize Computer Use bridge for executing function calls
		self.computer_use_bridge = ComputerUseBridge(
			screen_width=self.screen_width,
			screen_height=self.screen_height,
		)

		self.logger.info(
			f'🖱️  ComputerUseAgent initialized with Computer Use function calling '
			f'(max_iterations={self.max_function_iterations}, screen={self.screen_width}x{self.screen_height})'
		)

	def _load_computer_use_system_prompt(self, task: str) -> str:
		"""Load Computer Use-specific system prompt"""
		import importlib.resources

		try:
			# Load the prompt template from the markdown file
			with (
				importlib.resources.files('browser_use.llm.gemini_computer_use')
				.joinpath('computer_use_system_prompt.md')
				.open('r', encoding='utf-8') as f
			):
				prompt_template = f.read()

			# Replace {task} placeholder with actual task
			return prompt_template.replace('{task}', task)
		except Exception as e:
			self.logger.error(f'Failed to load Computer Use system prompt: {e}')
			# Fallback to inline prompt
			return f"""You are a browser automation agent using Google's Computer Use API.

Task: {task}

Use Computer Use functions (open_web_browser, navigate, click_at, type_text_at, get_browser_state, done, etc.) to complete the task.
Always call done(message="...") when finished with a summary of your findings.
DO NOT return JSON - only call functions."""

	@property
	def logger(self) -> logging.Logger:
		"""Get logger for this agent"""
		return logging.getLogger('browser_use.computer_use_agent')

	async def _execute_actions(self) -> None:
		"""Override to skip action execution - we already executed via Computer Use bridge.

		In Mode 2, actions are executed immediately via Actor API during the function calling loop,
		so we don't need the base agent to execute them again.
		"""
		# Actions were already executed via Computer Use bridge in _get_next_action
		# Set empty result if needed
		if self.state.last_result is None:
			self.state.last_result = []

		self.logger.debug('✅ Skipping _execute_actions (already executed via Computer Use bridge)')

	async def _get_next_action(self, browser_state_summary: BrowserStateSummary) -> None:
		"""Override to handle Computer Use function calls.

		Instead of requesting structured output (which blocks function calls),
		we request text responses and handle function calls directly.
		"""
		self.logger.info('🎯 ComputerUseAgent._get_next_action called')

		# Get initial messages from Browser Use message manager
		# These are Browser Use format messages that get serialized to Gemini format
		initial_messages = self._message_manager.get_messages()

		# Don't send initial screenshot - let the model call open_web_browser first
		# This matches the expected Computer Use workflow:
		# 1. Model calls open_web_browser (we return about:blank)
		# 2. Model sees empty browser in screenshot
		# 3. Model calls navigate to go to desired URL
		# 4. Model continues with task
		self.logger.info('Starting Computer Use loop - model will call open_web_browser first')

		self.logger.info(
			f'🤖 Step {self.state.n_steps}: Calling LLM with Computer Use enabled '
			f'({len(initial_messages)} initial messages, model: {self.llm.model})...'
		)

		# Track conversation history for function calling loop
		# We maintain our own Gemini Content list for the function calling iterations
		action_results: list[ActionResult] = []

		try:
			# Computer Use function calling loop
			# Use initial_messages for first call, then we'll maintain our own history
			current_messages = initial_messages

			for iteration in range(self.max_function_iterations):
				self.logger.debug(f'🔄 Computer Use iteration {iteration + 1}/{self.max_function_iterations}')
				self.logger.info(f'📋 Sending {len(current_messages)} messages to LLM')

				# Call LLM without output_format to allow function calls
				try:
					response = await asyncio.wait_for(
						self.llm.ainvoke(current_messages, output_format=None), timeout=self.settings.llm_timeout
					)
				except Exception as e:
					self.logger.error(f'❌ LLM call failed in iteration {iteration + 1}: {e}')
					raise

				self.logger.info(f'✅ Got response from Gemini (iteration {iteration + 1})')

				# Get the raw response from Gemini SDK
				# The response.completion should be the text or raw response
				raw_response = response.completion
				self.logger.info(f'🔍 DEBUG - Response type: {type(raw_response)}')

				# Check if we have function calls
				self.logger.info('🔍 DEBUG - Checking for function calls...')
				has_function_calls = self._has_function_calls(raw_response)
				self.logger.info(f'🔍 DEBUG - has_function_calls: {has_function_calls}')

				if not has_function_calls:
					# No function calls - this is the final response
					self.logger.info(f'✅ No function calls - got final text response: {str(raw_response)[:200]}')

					# Parse the text response into AgentOutput format
					try:
						model_output = await self._parse_text_to_agent_output(raw_response, browser_state_summary)
						self.state.last_model_output = model_output

						# Check again for paused/stopped state
						await self._check_stop_or_pause()

						# Handle callbacks
						await self._handle_post_llm_processing(browser_state_summary, initial_messages)

						return

					except Exception as e:
						self.logger.error(f'❌ Failed to parse text response: {e}')
						# Fall back to creating a simple agent output
						# Get the custom action model for this page
						custom_actions = self.tools.registry.create_action_model()

						# Create a simple model output with done action
						agent_output_model = AgentOutput.type_with_custom_actions(custom_actions)

						# Create done action data
						output_data = {
							'evaluation_previous_goal': 'Processing Computer Use results',
							'memory': f'Computer Use actions executed: {len(action_results)} actions',
							'next_goal': 'Continue task',
							'action': [
								{'done': {'text': f'Executed {len(action_results)} Computer Use actions', 'success': True}}
							],
						}

						model_output = agent_output_model.model_validate(output_data)
						self.state.last_model_output = model_output
						return

				# We have function calls - execute them
				self.logger.info(f'🖱️  Executing Computer Use function calls (iteration {iteration + 1})')

				# Extract function calls from response
				function_calls = self._extract_function_calls(raw_response)
				self.logger.info(f'📋 Found {len(function_calls)} function call(s)')
				for i, fc in enumerate(function_calls):
					self.logger.info(f'  Function call {i + 1}: {fc.name}({fc.args})')

				# Get current page
				assert self.browser_session is not None, 'BrowserSession is not set up'
				current_page = await self.browser_session.get_current_page()
				if not current_page:
					raise RuntimeError('No current page available for Computer Use actions')

				# Execute function calls via bridge
				try:
					self.logger.info(f'🔧 About to execute {len(function_calls)} function calls...')
					results = await self.computer_use_bridge.execute_function_calls(function_calls, current_page)
					self.logger.info(f'✅ Got {len(results)} results from bridge')
				except Exception as e:
					self.logger.error(f'❌ Error in bridge execution: {e}')
					import traceback

					traceback.print_exc()
					raise

				action_results.extend(results)
				self.logger.info(f'✅ Extended action_results, now have {len(action_results)} total')

				# Update last_result so the agent can track execution
				self.state.last_result = results
				self.logger.info('✅ Updated last_result')

				# Check if any result indicates done
				for result in results:
					if result.extracted_content and 'Done:' in result.extracted_content:
						self.logger.info('🎯 Detected done action, preparing final response')
						# Gemini called done - prepare final output and exit loop
						custom_actions = self.tools.registry.create_action_model()
						agent_output_model = AgentOutput.type_with_custom_actions(custom_actions)

						# Extract message from done result
						done_message = result.extracted_content.replace('Done: ', '').strip()

						output_data = {
							'evaluation_previous_goal': 'Completed Computer Use actions',
							'memory': f'Executed {len(action_results)} actions',
							'next_goal': 'Task completed',
							'action': [{'done': {'text': done_message, 'success': True}}],
						}

						model_output = agent_output_model.model_validate(output_data)
						self.state.last_model_output = model_output

						# Create final ActionResult with extracted_content for structured_output
						# Format as JSON so structured_output works automatically
						done_message_json = json.dumps({'result': done_message})

						final_result = ActionResult(
							is_done=True,
							success=True,
							extracted_content=done_message_json,  # JSON for structured_output
							long_term_memory=f'Task completed: {done_message[:100]}',
						)
						self.state.last_result = [final_result]

						# Handle callbacks
						await self._handle_post_llm_processing(browser_state_summary, initial_messages)
						return

				# Take screenshot after actions for next iteration
				# Computer Use Model REQUIRES PNG (not JPEG)
				# Resize to reduce size and avoid 503 errors
				self.logger.info('📸 Taking screenshot...')
				screenshot_b64 = await current_page.screenshot(format='png')
				screenshot_bytes = base64.b64decode(screenshot_b64)

				# Resize to reduce size if too large
				if len(screenshot_bytes) > self.screenshot_size_threshold:
					import io

					from PIL import Image

					img = Image.open(io.BytesIO(screenshot_bytes))
					# Resize by configured ratio if too large
					new_size = (int(img.width * self.screenshot_resize_ratio), int(img.height * self.screenshot_resize_ratio))
					img = img.resize(new_size, Image.Resampling.LANCZOS)

					# Save back to bytes
					buffer = io.BytesIO()
					img.save(buffer, format='PNG', optimize=True)
					screenshot_bytes = buffer.getvalue()
					self.logger.info(f'✅ Screenshot resized to {len(screenshot_bytes)} bytes')

				self.logger.info(f'✅ Screenshot captured ({len(screenshot_bytes)} bytes, PNG)')

				# Create proper function responses for Gemini
				# Gemini Computer Use expects FunctionResponse format, not UserMessage
				from google.genai import types
				from google.genai.types import Content, Part

				# Create function responses for Gemini
				# IMPORTANT: Gemini expects function responses in a specific format:
				# - One Part per function call with function_response
				# - Screenshot is added as a separate image part, NOT inside function_response

				# CRITICAL: First add the assistant's message with function calls
				# Gemini expects: user → assistant (with function_call) → user (with function_response)
				# The raw_response already contains the assistant's message with function calls
				if hasattr(raw_response, 'candidates') and getattr(raw_response, 'candidates', None):
					assistant_content = raw_response.candidates[0].content  # type: ignore
					self.logger.info(
						f'🔍 DEBUG - Assistant content role: {assistant_content.role if hasattr(assistant_content, "role") else "NO ROLE"}'
					)
					self.logger.info(
						f'🔍 DEBUG - Assistant content parts: {len(assistant_content.parts) if hasattr(assistant_content, "parts") else 0}'
					)
					current_messages.append(assistant_content)  # type: ignore
					self.logger.info(f'✅ Added assistant message with function calls, now have {len(current_messages)} messages')
				response_parts = []

				for i, fc in enumerate(function_calls):
					result = results[i] if i < len(results) else results[0]  # Use first result as fallback

					# Build response data
					response_data = {
						'url': await current_page.get_url(),
						'status': 'error' if result.error else 'success',
					}

					if result.error:
						response_data['error'] = result.error
					if result.extracted_content:
						response_data['message'] = result.extracted_content

					# Create FunctionResponsePart with screenshot INSIDE the function response
					screenshot_response_part = types.FunctionResponsePart(
						inline_data=types.FunctionResponseBlob(  # type: ignore
							mime_type='image/png',  # Computer Use requires PNG
							data=screenshot_bytes,
						)
					)

					# Create function response WITH screenshot in parts
					fr = types.FunctionResponse(
						name=fc.name,
						response=response_data,
						parts=[screenshot_response_part],  # Screenshot goes here!
					)
					response_parts.append(Part(function_response=fr))

				self.logger.info(f'✅ Created {len(function_calls)} function response(s) + 1 screenshot')

				# Create Content with all parts
				function_response_message = Content(
					role='user',  # Function responses are sent as user messages in Gemini
					parts=response_parts,
				)

				# Add to input messages
				current_messages.append(function_response_message)  # type: ignore
				self.logger.info('✅ Appended function responses to input_messages')

				self.logger.info(f'✅ Executed {len(results)} action(s), continuing conversation...')

			# If we hit max iterations, stop
			self.logger.warning(f'⚠️  Reached maximum Computer Use iterations ({self.max_function_iterations})')

			# Create a final model output from what we have
			custom_actions = self.tools.registry.create_action_model()
			agent_output_model = AgentOutput.type_with_custom_actions(custom_actions)

			output_data = {
				'evaluation_previous_goal': 'Executed Computer Use actions',
				'memory': f'Completed {len(action_results)} Computer Use actions',
				'next_goal': 'Task continuation',
				'action': [{'done': {'text': f'Completed {len(action_results)} Computer Use actions', 'success': False}}],
			}

			model_output = agent_output_model.model_validate(output_data)
			self.state.last_model_output = model_output

		except TimeoutError:
			raise TimeoutError(
				f'LLM call timed out after {self.settings.llm_timeout} seconds. Keep your thinking and output short.'
			)

	def _has_function_calls(self, response: Any) -> bool:
		"""Check if response contains Computer Use function calls"""
		# For text responses, there are no function calls
		if isinstance(response, str):
			return False

		# Check if it's a Gemini response with candidates
		if hasattr(response, 'candidates') and response.candidates:
			candidate = response.candidates[0]
			if candidate.content and candidate.content.parts:
				return any(hasattr(part, 'function_call') and part.function_call for part in candidate.content.parts)

		return False

	def _extract_function_calls(self, response: Any) -> list[Any]:
		"""Extract function calls from Gemini response"""
		function_calls = []

		if hasattr(response, 'candidates') and response.candidates:
			candidate = response.candidates[0]
			if candidate.content and candidate.content.parts:
				for part in candidate.content.parts:
					if hasattr(part, 'function_call') and part.function_call:
						function_calls.append(part.function_call)

		return function_calls

	async def _parse_text_to_agent_output(self, response: str | Any, browser_state: BrowserStateSummary) -> AgentOutput:  # noqa: ARG002
		"""Parse text response into AgentOutput format.

		This tries to extract JSON from the text, or creates a reasonable AgentOutput.
		"""
		# If response is not a string, try to get text from it
		if not isinstance(response, str):
			if hasattr(response, 'text'):
				response = response.text
			elif hasattr(response, 'completion'):
				response = response.completion
			else:
				response = str(response)

		# Try to find JSON in the response
		text = response.strip()

		# Remove markdown code blocks
		if text.startswith('```json') and text.endswith('```'):
			text = text[7:-3].strip()
		elif text.startswith('```') and text.endswith('```'):
			text = text[3:-3].strip()

		# Try to parse JSON
		try:
			data = json.loads(text)

			# Try to create AgentOutput from parsed data
			# Get the action model type for this page
			custom_actions = self.tools.registry.create_action_model()

			agent_output_model = AgentOutput.type_with_custom_actions(custom_actions)
			return agent_output_model.model_validate(data)

		except (json.JSONDecodeError, ValueError) as e:
			self.logger.debug(f'Could not parse JSON from response: {e}, using fallback')

			# Fallback: Create a simple AgentOutput with done action
			custom_actions = self.tools.registry.create_action_model()
			agent_output_model = AgentOutput.type_with_custom_actions(custom_actions)

			output_data = {
				'evaluation_previous_goal': 'Computer Use actions executed',
				'memory': f'Completed actions: {response[:100]}...',
				'next_goal': 'Continue task',
				'action': [{'done': {'text': f'Task step completed: {response[:100]}...', 'success': True}}],
			}

			return agent_output_model.model_validate(output_data)
