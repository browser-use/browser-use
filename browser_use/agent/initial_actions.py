import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from browser_use.agent.runtime.tools import NativeToolResult
from browser_use.agent.views import (
	ActionResult,
	AgentHistory,
	AgentHistoryList,
	AgentSettings,
	AgentState,
	BrowserStateHistory,
	StepMetadata,
)
from browser_use.agent.views import (
	AgentOutput as AgentOutputModel,
)
from browser_use.llm.messages import ToolCall
from browser_use.tools.registry.views import ActionModel as ActionModelType
from browser_use.tools.service import Tools


class AgentInitialActionsMixin:
	logger: logging.Logger
	initial_actions: list[ActionModelType] | None
	initial_url: str | None
	state: AgentState
	settings: AgentSettings
	AgentOutput: type[AgentOutputModel]
	ActionModel: type[ActionModelType]
	history: AgentHistoryList
	tools: Tools[Any]
	multi_act: Callable[[list[ActionModelType]], Awaitable[list[ActionResult]]]
	multi_act_action_models_native: Callable[
		[list[ActionModelType]], Awaitable[tuple[list[ActionResult], list[NativeToolResult], list[ToolCall]]]
	]

	def _extract_start_url(self, task: str) -> str | None:
		"""Extract URL from task string using naive pattern matching."""

		# Remove email addresses from task before looking for URLs
		task_without_emails = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '', task)

		# Look for common URL patterns
		patterns = [
			r'https?://[^\s<>"\']+',  # Full URLs with http/https
			r'(?:www\.)?[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}(?:/[^\s<>"\']*)?',  # Domain names with subdomains and optional paths
		]

		# File extensions that should be excluded from URL detection
		# These are likely files rather than web pages to navigate to
		excluded_extensions = {
			# Documents
			'pdf',
			'doc',
			'docx',
			'xls',
			'xlsx',
			'ppt',
			'pptx',
			'odt',
			'ods',
			'odp',
			# Text files
			'txt',
			'md',
			'csv',
			'json',
			'xml',
			'yaml',
			'yml',
			# Archives
			'zip',
			'rar',
			'7z',
			'tar',
			'gz',
			'bz2',
			'xz',
			# Images
			'jpg',
			'jpeg',
			'png',
			'gif',
			'bmp',
			'svg',
			'webp',
			'ico',
			# Audio/Video
			'mp3',
			'mp4',
			'avi',
			'mkv',
			'mov',
			'wav',
			'flac',
			'ogg',
			# Code/Data
			'py',
			'js',
			'css',
			'java',
			'cpp',
			# Academic/Research
			'bib',
			'bibtex',
			'tex',
			'latex',
			'cls',
			'sty',
			# Other common file types
			'exe',
			'msi',
			'dmg',
			'pkg',
			'deb',
			'rpm',
			'iso',
			# GitHub/Project paths
			'polynomial',
		}

		excluded_words = {
			'never',
			'dont',
			'not',
			"don't",
		}

		found_urls = []
		for pattern in patterns:
			matches = re.finditer(pattern, task_without_emails)
			for match in matches:
				url = match.group(0)
				original_position = match.start()  # Store original position before URL modification

				# Remove trailing punctuation that's not part of URLs
				url = re.sub(r'[.,;:!?()\[\]]+$', '', url)

				# Check if URL ends with a file extension that should be excluded
				url_lower = url.lower()
				should_exclude = False
				for ext in excluded_extensions:
					if f'.{ext}' in url_lower:
						should_exclude = True
						break

				if should_exclude:
					self.logger.debug(f'Excluding URL with file extension from auto-navigation: {url}')
					continue

				# If in the 20 characters before the url position is a word in excluded_words skip to avoid "Never go to this url"
				context_start = max(0, original_position - 20)
				context_text = task_without_emails[context_start:original_position]
				if any(word.lower() in context_text.lower() for word in excluded_words):
					self.logger.debug(
						f'Excluding URL with word in excluded words from auto-navigation: {url} (context: "{context_text.strip()}")'
					)
					continue

				# Add https:// if missing (after excluded words check to avoid position calculation issues)
				if not url.startswith(('http://', 'https://')):
					url = 'https://' + url

				found_urls.append(url)

		unique_urls = list(set(found_urls))
		# If multiple URLs found, skip directly_open_urling
		if len(unique_urls) > 1:
			self.logger.debug(f'Multiple URLs found ({len(found_urls)}), skipping directly_open_url to avoid ambiguity')
			return None

		# If exactly one URL found, return it
		if len(unique_urls) == 1:
			return unique_urls[0]

		return None

	async def _execute_initial_actions(self) -> None:
		# Execute initial actions if provided
		if self.initial_actions and not self.state.follow_up_task:
			self.logger.debug(f'⚡ Executing {len(self.initial_actions)} initial actions...')
			native_tool_calls: list[ToolCall] = []
			native_tool_results: list[NativeToolResult] = []
			if self.settings.use_native_tool_calls:
				result, native_tool_results, native_tool_calls = await self.multi_act_action_models_native(self.initial_actions)
			else:
				result = await self.multi_act(self.initial_actions)
			# update result 1 to mention that its was automatically loaded
			if result and self.initial_url and result[0].long_term_memory:
				result[0].long_term_memory = f'Found initial url and automatically loaded it. {result[0].long_term_memory}'
			self.state.last_result = result

			# Save initial actions to history as step 0 for rerun capability
			# Skip browser state capture for initial actions (usually just URL navigation)
			if self.settings.flash_mode:
				model_output = self.AgentOutput(
					evaluation_previous_goal=None,
					memory='Initial navigation',
					next_goal=None,
					action=self.initial_actions,
				)
			else:
				model_output = self.AgentOutput(
					evaluation_previous_goal='Start',
					memory=None,
					next_goal='Initial navigation',
					action=self.initial_actions,
				)

			if native_tool_calls:
				model_output.set_native_tool_calls(native_tool_calls)
				model_output.set_native_tool_results(native_tool_results)
			self.state.last_model_output = model_output

			metadata = StepMetadata(step_number=0, step_start_time=time.time(), step_end_time=time.time(), step_interval=None)

			# Create minimal browser state history for initial actions
			state_history = BrowserStateHistory(
				url=self.initial_url or '',
				title='Initial Actions',
				tabs=[],
				interacted_element=[None] * len(self.initial_actions),  # No DOM elements needed
				screenshot_path=None,
			)

			history_item = AgentHistory(
				model_output=model_output,
				result=result,
				state=state_history,
				metadata=metadata,
			)

			self.history.add_item(history_item)
			self.logger.debug('📝 Saved initial actions to history as step 0')
			self.logger.debug('Initial actions completed')

	def _convert_initial_actions(self, actions: list[dict[str, dict[str, Any]]]) -> list[ActionModelType]:
		"""Convert dictionary-based actions to ActionModel instances"""
		converted_actions = []
		action_model = self.ActionModel
		for action_dict in actions:
			# Each action_dict should have a single key-value pair
			action_name = next(iter(action_dict))
			params = action_dict[action_name]

			# Get the parameter model for this action from registry
			action_info = self.tools.registry.registry.actions[action_name]
			param_model = action_info.param_model

			# Create validated parameters using the appropriate param model
			validated_params = param_model(**params)

			# Create ActionModel instance with the validated parameters
			action_model = self.ActionModel(**{action_name: validated_params})
			converted_actions.append(action_model)

		return converted_actions
