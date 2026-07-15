"""Action executor — handles action execution and rerun logic.

Extracted from Agent.service for modularity.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import logging
import time
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
	from browser_use.agent.pipeline import StepPipeline
	from browser_use.agent.service import Agent

from browser_use.agent.views import (
	ActionResult,
	AgentHistory,
	AgentHistoryList,
	AgentStepInfo,
	RerunSummaryAction,
)
from browser_use.browser.views import BrowserStateSummary
from browser_use.dom.views import DOMInteractedElement, MatchLevel
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import BaseMessage
from browser_use.tools.registry.views import ActionModel

logger = logging.getLogger(__name__)


class ActionExecutor:
	"""Handles action execution, rerun, and step-level orchestration."""

	def __init__(self, agent: Agent, pipeline: StepPipeline) -> None:
		self._agent = agent
		self._pipeline = pipeline

	# ── Step execution ─────────────────────────────────────────────────
	async def execute_step(
		self,
		step: int,
		max_steps: int,
		step_info: AgentStepInfo,
		on_step_start: Callable | None = None,
		on_step_end: Callable | None = None,
	) -> bool:
		"""Execute a single step with timeout."""
		if on_step_start is not None:
			await on_step_start(self._agent)

		await self._pipeline.demo_mode_log(
			f'Starting step {step + 1}/{max_steps}',
			'info',
			{'step': step + 1, 'total_steps': max_steps},
		)
		self._agent.logger.debug(f'\U0001f6b6 Starting step {step + 1}/{max_steps}...')

		try:
			await asyncio.wait_for(
				self._pipeline.execute(step_info),
				timeout=self._agent.settings.step_timeout,
			)
			self._agent.logger.debug(f'\u2705 Completed step {step + 1}/{max_steps}')
		except TimeoutError:
			error_msg = f'Step {step + 1} timed out after {self._agent.settings.step_timeout} seconds'
			self._agent.logger.error(f'\u23f0 {error_msg}')
			await self._pipeline.demo_mode_log(error_msg, 'error', {'step': step + 1})
			self._agent.state.consecutive_failures += 1
			self._agent.state.last_result = [ActionResult(error=error_msg)]
			if self._agent.state.n_steps == step + 1:
				self._agent.state.n_steps += 1

		if on_step_end is not None:
			await on_step_end(self._agent)

		if self._agent.history.is_done():
			await self.log_completion()
			if self._agent.settings.use_judge:
				await self._agent._judge_and_log()
			if self._agent.register_done_callback:
				if inspect.iscoroutinefunction(self._agent.register_done_callback):
					await self._agent.register_done_callback(self._agent.history)
				else:
					self._agent.register_done_callback(self._agent.history)
			return True
		return False

	# ── Multi-action execution ──────────────────────────────────────────
	async def multi_act(self, actions: list[ActionModel]) -> list[ActionResult]:
		"""Execute multiple actions with page-change guards.

		Two layers of protection prevent executing actions against stale DOM:
		  1. Static flag: actions tagged with terminates_sequence=True (navigate, search, go_back, switch)
		     automatically abort remaining queued actions.
		  2. Runtime detection: after every action, the current URL and focused target are compared
		     to pre-action values. Any change aborts the remaining queue.
		"""
		results: list[ActionResult] = []
		total_actions = len(actions)

		assert self._agent.browser_session is not None, 'BrowserSession is not set up'
		try:
			if (
				self._agent.browser_session._cached_browser_state_summary is not None
				and self._agent.browser_session._cached_browser_state_summary.dom_state is not None
			):
				cached_selector_map = dict(
					self._agent.browser_session._cached_browser_state_summary.dom_state.selector_map
				)
			else:
				cached_selector_map = {}
		except Exception as e:
			self._agent.logger.error(f'Error getting cached selector map: {e}')
			cached_selector_map = {}

		for i, action in enumerate(actions):
			action_data = action.model_dump(exclude_unset=True)
			action_name = next(iter(action_data.keys())) if action_data else 'unknown'

			if i > 0:
				if action_data.get('done') is not None:
					msg = f'Done action is allowed only as a single action - stopped after action {i} / {total_actions}.'
					self._agent.logger.debug(msg)
					break

			if i > 0:
				self._agent.logger.debug(
					f'Waiting {self._agent.browser_profile.wait_between_actions} seconds between actions'
				)
				await asyncio.sleep(self._agent.browser_profile.wait_between_actions)

			try:
				await self._pipeline.check_stop_or_pause()
				await self._log_action(action, action_name, i + 1, total_actions)

				pre_action_url = await self._agent.browser_session.get_current_page_url()
				pre_action_focus = self._agent.browser_session.agent_focus_target_id

				result = await self._agent.tools.act(
					action=action,
					browser_session=self._agent.browser_session,
					file_system=self._agent.file_system,
					page_extraction_llm=self._agent.settings.page_extraction_llm,
					sensitive_data=self._agent.sensitive_data,
					available_file_paths=self._agent.available_file_paths,
					extraction_schema=self._agent.extraction_schema,
				)

				if result.error:
					await self._pipeline.demo_mode_log(
						f'Action "{action_name}" failed: {result.error}',
						'error',
						{'action': action_name, 'step': self._agent.state.n_steps},
					)
				elif result.is_done:
					completion_text = result.long_term_memory or result.extracted_content or 'Task marked as done.'
					level = 'success' if result.success is not False else 'warning'
					await self._pipeline.demo_mode_log(
						completion_text, level, {'action': action_name, 'step': self._agent.state.n_steps},
					)

				results.append(result)
				if results[-1].is_done or results[-1].error or i == total_actions - 1:
					break

				# Page-change guards
				registered_action = self._agent.tools.registry.registry.actions.get(action_name)
				if registered_action and registered_action.terminates_sequence:
					self._agent.logger.info(
						f'Action "{action_name}" terminates sequence \u2014 skipping {total_actions - i - 1} remaining action(s)'
					)
					break

				post_action_url = await self._agent.browser_session.get_current_page_url()
				post_action_focus = self._agent.browser_session.agent_focus_target_id

				if post_action_url != pre_action_url or post_action_focus != pre_action_focus:
					self._agent.logger.info(
						f'Page changed after "{action_name}" \u2014 skipping {total_actions - i - 1} remaining action(s)'
					)
					break

			except Exception as e:
				if isinstance(e, InterruptedError):
					raise
				if self._pipeline.is_connection_like_error(e):
					raise
				self._agent.logger.error(f'\u274c Executing action {i + 1} failed -> {type(e).__name__}: {e}')
				await self._pipeline.demo_mode_log(
					f'Action "{action_name}" raised {type(e).__name__}: {e}',
					'error',
					{'action': action_name, 'step': self._agent.state.n_steps},
				)
				results.append(ActionResult(error=f'{type(e).__name__}: {e}'))
				return results

		return results

	async def _log_action(self, action, action_name: str, action_num: int, total_actions: int) -> None:
		"""Log an action with its parameters."""
		action_data = action.model_dump(exclude_unset=True)
		reset = '\x1b[0m'
		cyan = '\x1b[36m'
		magenta = '\x1b[35m'
		action_header = f'Step {self._agent.state.n_steps} | Action {action_num}/{total_actions} | {action_name}'

		param_parts: list[str] = []
		plain_param_parts: list[str] = []
		for param_name, value in action_data.get(action_name, {}).items():
			if isinstance(value, str) and len(value) > 150:
				display_value = value[:150] + '...'
			elif isinstance(value, list) and len(str(value)) > 200:
				display_value = str(value)[:200] + '...'
			else:
				display_value = value
			param_parts.append(f'{magenta}{param_name}{reset}: {display_value}')
			plain_param_parts.append(f'{param_name}: {display_value}')

		if param_parts:
			params_string = ', '.join(param_parts)
			self._agent.logger.info(f'  {action_header} {params_string}')
		else:
			self._agent.logger.info(f'  {action_header}')

		if self._agent._demo_mode_enabled:
			plain_header = f'Step {self._agent.state.n_steps} | Action {action_num}/{total_actions} | {action_name}'
			panel_message = plain_header
			if plain_param_parts:
				panel_message = f'{panel_message} {", ".join(plain_param_parts)}'
			await self._pipeline.demo_mode_log(panel_message.strip(), 'action', {'action': action_name, 'step': self._agent.state.n_steps})

	async def log_completion(self) -> None:
		"""Log task completion."""
		if self._agent.history.is_successful():
			self._agent.logger.info('\u2705 Task completed successfully')
			await self._pipeline.demo_mode_log('Task completed successfully', 'success', {'tag': 'task'})

	# ── Rerun ───────────────────────────────────────────────────────────

	async def _execute_ai_step(
		self,
		query: str,
		include_screenshot: bool = False,
		extract_links: bool = False,
		ai_step_llm: BaseChatModel | None = None,
	) -> ActionResult:
		"""
		Execute an AI step during rerun to re-evaluate extract actions.
		Analyzes full page DOM/markdown + optional screenshot.

		Args:
			query: What to analyze or extract from the current page
			include_screenshot: Whether to include screenshot in analysis
			extract_links: Whether to include links in markdown extraction
			ai_step_llm: Optional LLM to use. If not provided, uses agent's LLM

		Returns:
			ActionResult with extracted content
		"""
		from browser_use.agent.prompts import get_ai_step_system_prompt, get_ai_step_user_prompt, get_rerun_summary_message
		from browser_use.llm.messages import SystemMessage, UserMessage
		from browser_use.utils import sanitize_surrogates

		# Use provided LLM or agent's LLM
		llm = ai_step_llm or self._agent.llm
		self._agent.logger.debug(f'Using LLM for AI step: {llm.model}')

		# Extract clean markdown
		try:
			
			from browser_use.dom.markdown_extractor import extract_clean_markdown
			content, content_stats = await extract_clean_markdown(
				browser_session=self._agent.browser_session, extract_links=extract_links
			)
		except Exception as e:
			return ActionResult(error=f'Could not extract clean markdown: {type(e).__name__}: {e}')

		# Get screenshot if requested
		screenshot_b64 = None
		if include_screenshot:
			try:
				screenshot = await self._agent.browser_session.take_screenshot(full_page=False)
				if screenshot:
					import base64

					screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')
			except Exception as e:
				self._agent.logger.warning(f'Failed to capture screenshot for ai_step: {e}')

		# Build prompt with content stats
		original_html_length = content_stats['original_html_chars']
		initial_markdown_length = content_stats['initial_markdown_chars']
		final_filtered_length = content_stats['final_filtered_chars']
		chars_filtered = content_stats['filtered_chars_removed']

		stats_summary = f"""Content processed: {original_html_length:,} HTML chars → {initial_markdown_length:,} initial markdown → {final_filtered_length:,} filtered markdown"""
		if chars_filtered > 0:
			stats_summary += f' (filtered {chars_filtered:,} chars of noise)'

		# Sanitize content
		content = sanitize_surrogates(content)
		query = sanitize_surrogates(query)

		# Get prompts from prompts.py
		from browser_use.agent.prompts import get_ai_step_system_prompt, get_ai_step_user_prompt, get_rerun_summary_message
		system_prompt = get_ai_step_system_prompt()
		prompt_text = get_ai_step_user_prompt(query, stats_summary, content)

		# Build user message with optional screenshot
		if screenshot_b64:
			user_message = get_rerun_summary_message(prompt_text, screenshot_b64)
		else:
			user_message = UserMessage(content=prompt_text)

		try:
			import asyncio

			response = await asyncio.wait_for(llm.ainvoke([SystemMessage(content=system_prompt), user_message]), timeout=120.0)

			current_url = await self._agent.browser_session.get_current_page_url()
			extracted_content = (
				f'<url>\n{current_url}\n</url>\n<query>\n{query}\n</query>\n<result>\n{response.completion}\n</result>'
			)

			# Simple memory handling
			MAX_MEMORY_LENGTH = 1000
			if len(extracted_content) < MAX_MEMORY_LENGTH:
				memory = extracted_content
				include_extracted_content_only_once = False
			else:
				file_name = await self._agent.file_system.save_extracted_content(extracted_content)
				memory = f'Query: {query}\nContent in {file_name} and once in <read_state>.'
				include_extracted_content_only_once = True

			self._agent.logger.info(f'🤖 AI Step: {memory}')
			return ActionResult(
				extracted_content=extracted_content,
				include_extracted_content_only_once=include_extracted_content_only_once,
				long_term_memory=memory,
			)
		except Exception as e:
			self._agent.logger.warning(f'Failed to execute AI step: {e.__class__.__name__}: {e}')
			self._agent.logger.debug('Full error traceback:', exc_info=True)
			return ActionResult(error=f'AI step failed: {e}')


	async def _execute_history_step(
		self,
		history_item: AgentHistory,
		delay: float,
		ai_step_llm: BaseChatModel | None = None,
		wait_for_elements: bool = False,
	) -> list[ActionResult]:
		"""Execute a single step from history with element validation.

		For extract actions, uses AI to re-evaluate the content since page content may have changed.

		Args:
			history_item: The history step to execute
			delay: Delay before executing the step
			ai_step_llm: Optional LLM to use for AI steps
			wait_for_elements: If True, wait for minimum elements before element matching
		"""
		assert self._agent.browser_session is not None, 'BrowserSession is not set up'

		await asyncio.sleep(delay)

		# Optionally wait for minimum elements before element matching (useful for SPAs)
		if wait_for_elements:
			# Determine if we need to wait for elements (actions that interact with DOM elements)
			needs_element_matching = False
			if history_item.model_output:
				for i, action in enumerate(history_item.model_output.action):
					action_data = action.model_dump(exclude_unset=True)
					action_name = next(iter(action_data.keys()), None)
					# Actions that need element matching
					if action_name in ('click', 'input', 'hover', 'select_option', 'drag_and_drop'):
						historical_elem = (
							history_item.state.interacted_element[i] if i < len(history_item.state.interacted_element) else None
						)
						if historical_elem is not None:
							needs_element_matching = True
							break

			# If we need element matching, wait for minimum elements before proceeding
			if needs_element_matching:
				min_elements = self._count_expected_elements_from_history(history_item)
				if min_elements > 0:
					state = await self._wait_for_minimum_elements(min_elements, timeout=15.0, poll_interval=1.0)
				else:
					state = await self._agent.browser_session.get_browser_state_summary(include_screenshot=False)
			else:
				state = await self._agent.browser_session.get_browser_state_summary(include_screenshot=False)
		else:
			state = await self._agent.browser_session.get_browser_state_summary(include_screenshot=False)
		if not state or not history_item.model_output:
			raise ValueError('Invalid state or model output')

		results = []
		pending_actions = []

		for i, action in enumerate(history_item.model_output.action):
			# Check if this is an extract action - use AI step instead
			action_data = action.model_dump(exclude_unset=True)
			action_name = next(iter(action_data.keys()), None)

			if action_name == 'extract':
				# Execute any pending actions first to maintain correct order
				# (e.g., if step is [click, extract], click must happen before extract)
				if pending_actions:
					batch_results = await self.multi_act(pending_actions)
					results.extend(batch_results)
					pending_actions = []

				# Now execute AI step for extract action
				extract_params = action_data['extract']
				query = extract_params.get('query', '')
				extract_links = extract_params.get('extract_links', False)

				self._agent.logger.info(f'🤖 Using AI step for extract action: {query[:50]}...')
				ai_result = await self._execute_ai_step(
					query=query,
					include_screenshot=False,  # Match original extract behavior
					extract_links=extract_links,
					ai_step_llm=ai_step_llm,
				)
				results.append(ai_result)
			else:
				# For non-extract actions, update indices and collect for batch execution
				historical_elem = history_item.state.interacted_element[i]
				updated_action = await self._update_action_indices(
					historical_elem,
					action,
					state,
				)
				if updated_action is None:
					# Build informative error message with diagnostic info
					elem_info = self._format_element_for_error(historical_elem)
					selector_map = state.dom_state.selector_map or {}
					selector_count = len(selector_map)

					# Find elements with same node_name for diagnostics
					hist_node = historical_elem.node_name.lower() if historical_elem else ''
					similar_elements = []
					if historical_elem and historical_elem.attributes:
						for idx, elem in selector_map.items():
							if elem.node_name.lower() == hist_node and elem.attributes:
								elem_aria = elem.attributes.get('aria-label', '')
								if elem_aria:
									similar_elements.append(f'{idx}:{elem_aria[:30]}')
									if len(similar_elements) >= 5:
										break

					diagnostic = ''
					if similar_elements:
						diagnostic = f'\n  Available <{hist_node.upper()}> with aria-label: {similar_elements}'
					elif hist_node:
						same_node_count = sum(1 for e in selector_map.values() if e.node_name.lower() == hist_node)
						diagnostic = (
							f'\n  Found {same_node_count} <{hist_node.upper()}> elements (none with matching identifiers)'
						)

					raise ValueError(
						f'Could not find matching element for action {i} in current page.\n'
						f'  Looking for: {elem_info}\n'
						f'  Page has {selector_count} interactive elements.{diagnostic}\n'
						f'  Tried: EXACT hash → STABLE hash → XPATH → AX_NAME → ATTRIBUTE matching'
					)
				pending_actions.append(updated_action)

		# Execute any remaining pending actions
		if pending_actions:
			batch_results = await self.multi_act(pending_actions)
			results.extend(batch_results)

		return results


	async def _wait_for_minimum_elements(
		self,
		min_elements: int,
		timeout: float = 30.0,
		poll_interval: float = 1.0,
	) -> BrowserStateSummary | None:
		"""Wait for the page to have at least min_elements interactive elements.

		This helps handle SPA pages where shadow DOM and dynamic content
		may not be immediately available even when document.readyState is 'complete'.

		Args:
			min_elements: Minimum number of interactive elements to wait for
			timeout: Maximum time to wait in seconds
			poll_interval: Time between polling attempts in seconds

		Returns:
			BrowserStateSummary if minimum elements found, None if timeout
		"""
		assert self._agent.browser_session is not None, 'BrowserSession is not set up'

		start_time = time.time()
		last_count = 0

		while (time.time() - start_time) < timeout:
			state = await self._agent.browser_session.get_browser_state_summary(include_screenshot=False)
			if state and state.dom_state.selector_map:
				current_count = len(state.dom_state.selector_map)
				if current_count >= min_elements:
					self._agent.logger.debug(f'✅ Page has {current_count} elements (needed {min_elements}), proceeding with action')
					return state
				if current_count != last_count:
					self._agent.logger.debug(
						f'⏳ Waiting for elements: {current_count}/{min_elements} '
						f'(timeout in {timeout - (time.time() - start_time):.1f}s)'
					)
					last_count = current_count
			await asyncio.sleep(poll_interval)

		# Return last state even if we didn't reach min_elements
		self._agent.logger.warning(f'⚠️ Timeout waiting for {min_elements} elements, proceeding with {last_count} elements')
		return await self._agent.browser_session.get_browser_state_summary(include_screenshot=False)


	def _count_expected_elements_from_history(self, history_item: AgentHistory) -> int:
		"""Estimate the minimum number of elements expected based on history.

		Uses the action indices from the history to determine the minimum
		number of elements the page should have. If an action targets index N,
		the page needs at least N+1 elements in the selector_map.
		"""
		if not history_item.model_output or not history_item.model_output.action:
			return 0

		max_index = -1  # Use -1 to indicate no index found yet
		for action in history_item.model_output.action:
			# Get the element index this action targets
			index = action.get_index()
			if index is not None:
				max_index = max(max_index, index)

		# Need at least max_index + 1 elements (indices are 0-based)
		# Cap at 50 to avoid waiting forever for very high indices
		# max_index >= 0 means we found at least one action with an index
		return min(max_index + 1, 50) if max_index >= 0 else 0


	async def _update_action_indices(
		self,
		historical_element: DOMInteractedElement | None,
		action: ActionModel,  # Type this properly based on your action model
		browser_state_summary: BrowserStateSummary,
	) -> ActionModel | None:
		"""
		Update action indices based on current page state.
		Returns updated action or None if element cannot be found.

		Cascading matching strategy (tries each level in order):
		1. EXACT: Full element_hash match (includes all attributes + ax_name)
		2. STABLE: Hash with dynamic CSS classes filtered out (focus, hover, animation, etc.)
		3. XPATH: XPath string match (structural position in DOM)
		4. AX_NAME: Accessible name match from accessibility tree (robust for dynamic menus)
		5. ATTRIBUTE: Unique attribute match (name, id, aria-label) for old history files
		"""
		if not historical_element or not browser_state_summary.dom_state.selector_map:
			return action

		selector_map = browser_state_summary.dom_state.selector_map
		highlight_index: int | None = None
		match_level: MatchLevel | None = None

		# Debug: log what we're looking for and what's available
		self._agent.logger.info(
			f'🔍 Searching for element: <{historical_element.node_name}> '
			f'hash={historical_element.element_hash} stable_hash={historical_element.stable_hash}'
		)
		# Log what elements are in selector_map for debugging
		if historical_element.node_name:
			hist_name = historical_element.node_name.lower()
			matching_nodes = [
				(idx, elem.node_name, elem.attributes.get('name') if elem.attributes else None)
				for idx, elem in selector_map.items()
				if elem.node_name.lower() == hist_name
			]
			self._agent.logger.info(
				f'🔍 Selector map has {len(selector_map)} elements, '
				f'{len(matching_nodes)} are <{hist_name.upper()}>: {matching_nodes}'
			)

		# Level 1: EXACT hash match
		for idx, elem in selector_map.items():
			if elem.element_hash == historical_element.element_hash:
				highlight_index = idx
				match_level = MatchLevel.EXACT
				break

		if highlight_index is None:
			self._agent.logger.debug(f'EXACT hash match failed (checked {len(selector_map)} elements)')

		# Level 2: STABLE hash match (dynamic classes filtered)
		# Use stored stable_hash (computed at save time from EnhancedDOMTreeNode - single source of truth)
		if highlight_index is None and historical_element.stable_hash is not None:
			for idx, elem in selector_map.items():
				if elem.compute_stable_hash() == historical_element.stable_hash:
					highlight_index = idx
					match_level = MatchLevel.STABLE
					self._agent.logger.info('Element matched at STABLE level (dynamic classes filtered)')
					break
			if highlight_index is None:
				self._agent.logger.debug('STABLE hash match failed')
		elif highlight_index is None:
			self._agent.logger.debug('STABLE hash match skipped (no stable_hash in history)')

		# Level 3: XPATH match
		if highlight_index is None and historical_element.x_path:
			for idx, elem in selector_map.items():
				if elem.xpath == historical_element.x_path:
					highlight_index = idx
					match_level = MatchLevel.XPATH
					self._agent.logger.info(f'Element matched at XPATH level: {historical_element.x_path}')
					break
			if highlight_index is None:
				self._agent.logger.debug(f'XPATH match failed for: {historical_element.x_path[-60:]}')

		# Level 4: ax_name (accessible name) match - robust for dynamic SPAs with menus
		# This uses the accessible name from the accessibility tree which is stable
		# even when DOM structure changes (e.g., dynamically generated menu items)
		if highlight_index is None and historical_element.ax_name:
			hist_name = historical_element.node_name.lower()
			hist_ax_name = historical_element.ax_name
			for idx, elem in selector_map.items():
				# Match by node type and accessible name
				elem_ax_name = elem.ax_node.name if elem.ax_node else None
				if elem.node_name.lower() == hist_name and elem_ax_name == hist_ax_name:
					highlight_index = idx
					match_level = MatchLevel.AX_NAME
					self._agent.logger.info(f'Element matched at AX_NAME level: "{hist_ax_name}"')
					break
			if highlight_index is None:
				# Log available ax_names for debugging
				same_type_ax_names = [
					(idx, elem.ax_node.name if elem.ax_node else None)
					for idx, elem in selector_map.items()
					if elem.node_name.lower() == hist_name and elem.ax_node and elem.ax_node.name
				]
				self._agent.logger.debug(
					f'AX_NAME match failed for <{hist_name.upper()}> ax_name="{hist_ax_name}". '
					f'Page has {len(same_type_ax_names)} <{hist_name.upper()}> with ax_names: '
					f'{same_type_ax_names[:5]}{"..." if len(same_type_ax_names) > 5 else ""}'
				)

		# Level 5: Unique attribute fallback (for old history files without stable_hash)
		if highlight_index is None and historical_element.attributes:
			hist_attrs = historical_element.attributes
			hist_name = historical_element.node_name.lower()

			# Try matching by unique identifiers: name, id, or aria-label
			for attr_key in ['name', 'id', 'aria-label']:
				if attr_key in hist_attrs and hist_attrs[attr_key]:
					for idx, elem in selector_map.items():
						if (
							elem.node_name.lower() == hist_name
							and elem.attributes
							and elem.attributes.get(attr_key) == hist_attrs[attr_key]
						):
							highlight_index = idx
							match_level = MatchLevel.ATTRIBUTE
							self._agent.logger.info(f'Element matched via {attr_key} attribute: {hist_attrs[attr_key]}')
							break
					if highlight_index is not None:
						break

			if highlight_index is None:
				tried_attrs = [k for k in ['name', 'id', 'aria-label'] if k in hist_attrs and hist_attrs[k]]
				# Log what was tried and what's available on the page for debugging
				same_node_elements = [
					(idx, elem.attributes.get('aria-label') or elem.attributes.get('id') or elem.attributes.get('name'))
					for idx, elem in selector_map.items()
					if elem.node_name.lower() == hist_name and elem.attributes
				]
				self._agent.logger.info(
					f'🔍 ATTRIBUTE match failed for <{hist_name.upper()}> '
					f'(tried: {tried_attrs}, looking for: {[hist_attrs.get(k) for k in tried_attrs]}). '
					f'Page has {len(same_node_elements)} <{hist_name.upper()}> elements with identifiers: '
					f'{same_node_elements[:5]}{"..." if len(same_node_elements) > 5 else ""}'
				)

		if highlight_index is None:
			return None

		old_index = action.get_index()
		if old_index != highlight_index:
			action.set_index(highlight_index)
			level_name = match_level.name if match_level else 'UNKNOWN'
			self._agent.logger.info(f'Element index updated {old_index} → {highlight_index} (matched at {level_name} level)')

		return action


	def _format_element_for_error(self, elem: DOMInteractedElement | None) -> str:
		"""Format element info for error messages during history rerun."""
		if elem is None:
			return '<no element recorded>'

		parts = [f'<{elem.node_name}>']

		# Add key identifying attributes
		if elem.attributes:
			for key in ['name', 'id', 'aria-label', 'type']:
				if key in elem.attributes and elem.attributes[key]:
					parts.append(f'{key}="{elem.attributes[key]}"')

		# Add hash info
		parts.append(f'hash={elem.element_hash}')
		if elem.stable_hash:
			parts.append(f'stable_hash={elem.stable_hash}')

		# Add xpath (truncated)
		if elem.x_path:
			xpath_short = elem.x_path if len(elem.x_path) <= 60 else f'...{elem.x_path[-57:]}'
			parts.append(f'xpath="{xpath_short}"')

		return ' '.join(parts)


	def _is_redundant_retry_step(
		self,
		current_item: AgentHistory,
		previous_item: AgentHistory | None,
		previous_step_succeeded: bool,
	) -> bool:
		"""
		Detect if current step is a redundant retry of the previous step.

		This handles cases where the original run needed to click the same element multiple
		times due to slow page response, but during replay the first click already succeeded.
		When the page has already navigated, subsequent retry clicks on the same element
		would fail because that element no longer exists.

		Returns True if:
		- Previous step succeeded
		- Both steps target the same element (by element_hash, stable_hash, or xpath)
		- Both steps perform the same action type (e.g., both are clicks)
		"""
		if not previous_item or not previous_step_succeeded:
			return False

		# Get interacted elements from both steps (first action in each)
		curr_elements = current_item.state.interacted_element
		prev_elements = previous_item.state.interacted_element

		if not curr_elements or not prev_elements:
			return False

		curr_elem = curr_elements[0] if curr_elements else None
		prev_elem = prev_elements[0] if prev_elements else None

		if not curr_elem or not prev_elem:
			return False

		# Check if same element by various matching strategies
		same_by_hash = curr_elem.element_hash == prev_elem.element_hash
		same_by_stable_hash = (
			curr_elem.stable_hash is not None
			and prev_elem.stable_hash is not None
			and curr_elem.stable_hash == prev_elem.stable_hash
		)
		same_by_xpath = curr_elem.x_path == prev_elem.x_path

		if not (same_by_hash or same_by_stable_hash or same_by_xpath):
			return False

		# Check if same action type
		curr_actions = current_item.model_output.action if current_item.model_output else []
		prev_actions = previous_item.model_output.action if previous_item.model_output else []

		if not curr_actions or not prev_actions:
			return False

		# Get the action type (first key in the action dict)
		curr_action_data = curr_actions[0].model_dump(exclude_unset=True)
		prev_action_data = prev_actions[0].model_dump(exclude_unset=True)

		curr_action_type = next(iter(curr_action_data.keys()), None)
		prev_action_type = next(iter(prev_action_data.keys()), None)

		if curr_action_type != prev_action_type:
			return False

		self._agent.logger.debug(
			f'🔄 Detected redundant retry: both steps target same element '
			f'<{curr_elem.node_name}> with action "{curr_action_type}"'
		)

		return True


	def _is_menu_opener_step(self, history_item: AgentHistory | None) -> bool:
		"""
		Detect if a step opens a dropdown/menu.

		Checks for common patterns indicating a menu opener:
		- Element has aria-haspopup attribute
		- Element has data-gw-click="toggleSubMenu" (Guidewire pattern)
		- Element has expand-button in class name
		- Element role is "menuitem" with aria-expanded

		Returns True if the step appears to open a dropdown/submenu.
		"""
		if not history_item or not history_item.state or not history_item.state.interacted_element:
			return False

		elem = history_item.state.interacted_element[0] if history_item.state.interacted_element else None
		if not elem:
			return False

		attrs = elem.attributes or {}

		# Check for common menu opener indicators
		if attrs.get('aria-haspopup') in ('true', 'menu', 'listbox'):
			return True
		if attrs.get('data-gw-click') == 'toggleSubMenu':
			return True
		if 'expand-button' in attrs.get('class', ''):
			return True
		if attrs.get('role') == 'menuitem' and attrs.get('aria-expanded') in ('false', 'true'):
			return True
		if attrs.get('role') == 'button' and attrs.get('aria-expanded') in ('false', 'true'):
			return True

		return False


	def _is_menu_item_element(self, elem: 'DOMInteractedElement | None') -> bool:
		"""
		Detect if an element is a menu item that appears inside a dropdown/menu.

		Checks for:
		- role="menuitem", "option", "menuitemcheckbox", "menuitemradio"
		- Element is inside a menu structure (has menu-related parent indicators)
		- ax_name is set (menu items typically have accessible names)

		Returns True if the element appears to be a menu item.
		"""
		if not elem:
			return False

		attrs = elem.attributes or {}

		# Check for menu item roles
		role = attrs.get('role', '')
		if role in ('menuitem', 'option', 'menuitemcheckbox', 'menuitemradio', 'treeitem'):
			return True

		# Elements in Guidewire menus have these patterns
		if 'gw-action--inner' in attrs.get('class', ''):
			return True
		if 'menuitem' in attrs.get('class', '').lower():
			return True

		# If element has an ax_name and looks like it could be in a menu
		# This is a softer check - only used if the previous step was a menu opener
		if elem.ax_name and elem.ax_name not in ('', None):
			# Common menu container classes
			elem_class = attrs.get('class', '').lower()
			if any(x in elem_class for x in ['dropdown', 'popup', 'menu', 'submenu', 'action']):
				return True

		return False


	async def _reexecute_menu_opener(
		self,
		opener_item: AgentHistory,
		ai_step_llm: 'BaseChatModel | None' = None,
	) -> bool:
		"""
		Re-execute a menu opener step to re-open a closed dropdown.

		This is used when a menu item can't be found because the dropdown
		closed during the wait between steps.

		Returns True if re-execution succeeded, False otherwise.
		"""
		try:
			self._agent.logger.info('🔄 Re-opening dropdown/menu by re-executing previous step...')
			# Use a minimal delay - we want to quickly re-open the menu
			await self._execute_history_step(opener_item, delay=0.5, ai_step_llm=ai_step_llm, wait_for_elements=False)
			# Small delay to let the menu render
			await asyncio.sleep(0.3)
			return True
		except Exception as e:
			self._agent.logger.warning(f'Failed to re-open dropdown: {e}')
			return False

	async def _close_browser_if_needed(self, results: list[ActionResult]) -> None:
		"""Add a summary and close the browser after rerun completion."""
		if results:
			summary = await self._generate_rerun_summary(self._agent.task, results)
			results.append(summary)

	async def _generate_rerun_summary(
		self, original_task: str, results: list[ActionResult],
		summary_llm: BaseChatModel | None = None,
	) -> ActionResult:
		"""Generate AI summary of rerun completion."""
		screenshot_b64 = None
		try:
			screenshot = await self._agent.browser_session.take_screenshot(full_page=False)
			if screenshot:
				screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')
		except Exception as e:
			self._agent.logger.warning(f'Failed to capture screenshot for rerun summary: {e}')

		error_count = sum(1 for r in results if r.error)
		success_count = len(results) - error_count

		from browser_use.agent.prompts import get_rerun_summary_prompt, get_rerun_summary_message
		prompt = get_rerun_summary_prompt(
			original_task=original_task,
			total_steps=len(results),
			success_count=success_count,
			error_count=error_count,
		)

		try:
			target_llm = summary_llm or self._agent.llm
			message = get_rerun_summary_message(prompt, screenshot_b64)
			messages: list[BaseMessage] = [message]
			try:
				kwargs: dict = {'output_format': RerunSummaryAction}
				response = await target_llm.ainvoke(messages, **kwargs)
				summary: RerunSummaryAction = response.completion  # type: ignore[assignment]
			except Exception:
				response = await target_llm.ainvoke(messages, None)
				response_text = response.completion
				summary = RerunSummaryAction(
					summary=response_text if isinstance(response_text, str) else str(response_text),
					success=error_count == 0,
					completion_status='complete' if error_count == 0 else ('partial' if success_count > 0 else 'failed'),
				)

			self._agent.logger.info(f'\U0001f4ca Rerun Summary: {summary.summary}')
			self._agent.logger.info(f'\U0001f4ca Status: {summary.completion_status} (success={summary.success})')
			return ActionResult(
				is_done=True,
				success=summary.success,
				extracted_content=summary.summary,
				long_term_memory=f'Rerun completed with status: {summary.completion_status}. {summary.summary[:100]}',
			)
		except Exception as e:
			self._agent.logger.warning(f'Failed to generate AI summary: {e.__class__.__name__}: {e}')
			return ActionResult(
				is_done=True,
				success=error_count == 0,
				extracted_content=f'Rerun completed: {success_count}/{len(results)} steps succeeded',
				long_term_memory=f'Rerun completed: {success_count} steps succeeded, {error_count} errors',
			)


	async def rerun_history(
		self,
		history: AgentHistoryList,
		max_retries: int = 3,
		skip_failures: bool = False,
		delay_between_actions: float = 2.0,
		max_step_interval: float = 45.0,
		summary_llm: BaseChatModel | None = None,
		ai_step_llm: BaseChatModel | None = None,
		wait_for_elements: bool = False,
	) -> list[ActionResult]:
		"""
		Rerun a saved history of actions with error handling and retry logic.

		Args:
		                history: The history to replay
		                max_retries: Maximum number of retries per action
		                skip_failures: Whether to skip failed actions or stop execution. When True, also skips
		                               steps that had errors in the original run (e.g., modal close buttons that
		                               auto-dismissed, or elements that became non-interactable)
		                delay_between_actions: Delay between actions in seconds (used when no saved interval)
		                max_step_interval: Maximum delay from saved step_interval (caps LLM time from original run)
		                summary_llm: Optional LLM to use for generating the final summary. If not provided, uses the agent's LLM
		                ai_step_llm: Optional LLM to use for AI steps (extract actions). If not provided, uses the agent's LLM
		                wait_for_elements: If True, wait for minimum number of elements before attempting element
		                               matching. Useful for SPA pages where shadow DOM content loads dynamically.
		                               Default is False.

		Returns:
		                List of action results (including AI summary as the final result)
		"""
		# Skip cloud sync session events for rerunning (we're replaying, not starting new)
		self._agent.state.session_initialized = True

		# Initialize browser session
		await self._agent.browser_session.start()

		results = []

		# Track previous step for redundant retry detection
		previous_item: AgentHistory | None = None
		previous_step_succeeded: bool = False

		try:
			for i, history_item in enumerate(history.history):
				goal = history_item.model_output.current_state.next_goal if history_item.model_output else ''
				step_num = history_item.metadata.step_number if history_item.metadata else i
				step_name = 'Initial actions' if step_num == 0 else f'Step {step_num}'

				# Determine step delay
				if history_item.metadata and history_item.metadata.step_interval is not None:
					# Cap the saved interval to max_step_interval (saved interval includes LLM time)
					step_delay = min(history_item.metadata.step_interval, max_step_interval)
					# Format delay nicely - show ms for values < 1s, otherwise show seconds
					if step_delay < 1.0:
						delay_str = f'{step_delay * 1000:.0f}ms'
					else:
						delay_str = f'{step_delay:.1f}s'
					if history_item.metadata.step_interval > max_step_interval:
						delay_source = f'capped to {delay_str} (saved was {history_item.metadata.step_interval:.1f}s)'
					else:
						delay_source = f'using saved step_interval={delay_str}'
				else:
					step_delay = delay_between_actions
					if step_delay < 1.0:
						delay_str = f'{step_delay * 1000:.0f}ms'
					else:
						delay_str = f'{step_delay:.1f}s'
					delay_source = f'using default delay={delay_str}'

				self._agent.logger.info(f'Replaying {step_name} ({i + 1}/{len(history.history)}) [{delay_source}]: {goal}')

				if (
					not history_item.model_output
					or not history_item.model_output.action
					or history_item.model_output.action == [None]
				):
					self._agent.logger.warning(f'{step_name}: No action to replay, skipping')
					results.append(ActionResult(error='No action to replay'))
					continue

				# Check if the original step had errors - skip if skip_failures is enabled
				original_had_error = any(r.error for r in history_item.result if r.error)
				if original_had_error and skip_failures:
					error_msgs = [r.error for r in history_item.result if r.error]
					self._agent.logger.warning(
						f'{step_name}: Original step had error(s), skipping (skip_failures=True): {error_msgs[0][:100] if error_msgs else "unknown"}'
					)
					results.append(
						ActionResult(
							error=f'Skipped - original step had error: {error_msgs[0][:100] if error_msgs else "unknown"}'
						)
					)
					continue

				# Check if this step is a redundant retry of the previous step
				# This handles cases where original run needed to click same element multiple times
				# due to slow page response, but during replay the first click already worked
				if self._is_redundant_retry_step(history_item, previous_item, previous_step_succeeded):
					self._agent.logger.info(f'{step_name}: Skipping redundant retry (previous step already succeeded with same element)')
					results.append(
						ActionResult(
							extracted_content='Skipped - redundant retry of previous step',
							include_in_memory=False,
						)
					)
					# Don't update previous_item/previous_step_succeeded - keep tracking the original step
					continue

				retry_count = 0
				step_succeeded = False
				menu_reopened = False  # Track if we've already tried reopening the menu
				# Exponential backoff: 5s base, doubling each retry, capped at 30s
				base_retry_delay = 5.0
				max_retry_delay = 30.0
				while retry_count < max_retries:
					try:
						result = await self._execute_history_step(history_item, step_delay, ai_step_llm, wait_for_elements)
						results.extend(result)
						step_succeeded = True
						break

					except Exception as e:
						error_str = str(e)
						retry_count += 1

						# Check if this is a "Could not find matching element" error for a menu item
						# If so, try to re-open the dropdown from the previous step before retrying
						if (
							not menu_reopened
							and 'Could not find matching element' in error_str
							and previous_item is not None
							and self._is_menu_opener_step(previous_item)
						):
							# Check if current step targets a menu item element
							curr_elements = history_item.state.interacted_element if history_item.state else []
							curr_elem = curr_elements[0] if curr_elements else None
							if self._is_menu_item_element(curr_elem):
								self._agent.logger.info(
									'🔄 Dropdown may have closed. Attempting to re-open by re-executing previous step...'
								)
								reopened = await self._reexecute_menu_opener(previous_item, ai_step_llm)
								if reopened:
									menu_reopened = True
									# Don't increment retry_count for the menu reopen attempt
									# Retry immediately with minimal delay
									retry_count -= 1
									step_delay = 0.5  # Use short delay after reopening
									self._agent.logger.info('🔄 Dropdown re-opened, retrying element match...')
									continue

						if retry_count == max_retries:
							error_msg = f'{step_name} failed after {max_retries} attempts: {error_str}'
							self._agent.logger.error(error_msg)
							# Always record the error in results so AI summary counts it correctly
							results.append(ActionResult(error=error_msg))
							if not skip_failures:
								raise RuntimeError(error_msg)
							# With skip_failures=True, continue to next step
						else:
							# Exponential backoff: 5s, 10s, 20s, ... capped at 30s
							retry_delay = min(base_retry_delay * (2 ** (retry_count - 1)), max_retry_delay)
							self._agent.logger.warning(
								f'{step_name} failed (attempt {retry_count}/{max_retries}), retrying in {retry_delay}s...'
							)
							await asyncio.sleep(retry_delay)

				# Update tracking for redundant retry detection
				previous_item = history_item
				previous_step_succeeded = step_succeeded

			# Generate AI summary of rerun completion
			self._agent.logger.info('🤖 Generating AI summary of rerun completion...')
			summary_result = await self._generate_rerun_summary(self._agent.task, results, summary_llm)
			results.append(summary_result)

			return results
		finally:
			# Always close resources, even on failure
			await self._agent.close()

