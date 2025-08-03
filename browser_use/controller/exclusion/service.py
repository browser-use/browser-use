# @file purpose: Deterministic tool exclusion service for browser-use
"""
Deterministic Tool Exclusion Service

This service implements comprehensive rules to exclude tools before sending them to the LLM
based on browser state, element availability, and other deterministic factors.
This reduces token usage and improves LLM response quality by only presenting relevant tools.
"""

import logging
from typing import Any

from browser_use.browser.views import BrowserStateSummary
from browser_use.controller.exclusion.views import ExclusionContext
from browser_use.filesystem.file_system import FileSystem

logger = logging.getLogger(__name__)


class ToolExclusionService:
	"""Service for determining which tools to exclude based on deterministic rules"""

	# Tool categories for easy reference
	GOOGLE_SHEETS_TOOLS = [
		'read_sheet_contents',
		'read_cell_contents',
		'update_cell_contents',
		'clear_cell_contents',
		'select_cell_or_range',
		'fallback_input_into_single_selected_cell',
	]

	TAB_MANAGEMENT_TOOLS = ['switch_tab', 'close_tab']

	FILE_SYSTEM_TOOLS = ['read_file', 'replace_file_str']

	ELEMENT_INTERACTION_TOOLS = ['click_element_by_index', 'input_text']

	DROPDOWN_TOOLS = ['get_dropdown_options', 'select_dropdown_option']

	SCROLL_TOOLS = ['scroll', 'scroll_to_text']

	NAVIGATION_TOOLS = ['go_back']

	CONTENT_TOOLS = ['extract_structured_data']

	UPLOAD_TOOLS = ['upload_file']

	# Tools that should never be excluded (critical functionality)
	NEVER_EXCLUDE = ['done', 'send_keys', 'go_to_url']

	def get_excluded_tools(self, context: ExclusionContext) -> list[str]:
		"""
		Get list of tools to exclude based on current context

		Args:
		    context: Current browser and agent context

		Returns:
		    List of tool names to exclude
		"""
		excluded_tools = []

		# Apply high confidence rules (definitive exclusions)
		excluded_tools.extend(self._apply_high_confidence_rules(context))

		# Apply medium confidence rules (probable exclusions)
		excluded_tools.extend(self._apply_medium_confidence_rules(context))

		# Apply low confidence rules (contextual exclusions)
		excluded_tools.extend(self._apply_low_confidence_rules(context))

		# Remove duplicates and ensure we never exclude critical tools
		excluded_tools = sorted(set(excluded_tools))
		excluded_tools = [tool for tool in excluded_tools if tool not in self.NEVER_EXCLUDE]

		if excluded_tools:
			logger.debug(f'Excluded {len(excluded_tools)} tools: {excluded_tools}')

		return excluded_tools

	def _apply_high_confidence_rules(self, context: ExclusionContext) -> list[str]:
		"""Apply high confidence exclusion rules (definitive exclusions)"""
		excluded = []

		# Domain-based exclusions for Google Sheets
		if not self._is_google_sheets_domain(context.browser_state.url):
			excluded.extend(self.GOOGLE_SHEETS_TOOLS)

		# Tab management exclusions
		if len(context.browser_state.tabs) <= 1:
			excluded.extend(self.TAB_MANAGEMENT_TOOLS)

		# File system exclusions
		if not context.file_system:
			excluded.extend(self.FILE_SYSTEM_TOOLS)

		# Upload tool exclusions
		if not context.available_file_paths or len(context.available_file_paths) == 0:
			excluded.extend(self.UPLOAD_TOOLS)

		# File content-based exclusions - exclude read/replace if no files exist
		if context.file_system and self._has_no_file_content(context.file_system):
			excluded.extend(['read_file', 'replace_file_str'])  # Keep write_file available

		return excluded

	def _apply_medium_confidence_rules(self, context: ExclusionContext) -> list[str]:
		"""Apply medium confidence exclusion rules (probable exclusions)"""
		excluded = []

		# Element interaction exclusions
		if not self._has_clickable_elements(context.browser_state):
			excluded.extend(self.ELEMENT_INTERACTION_TOOLS)

		# Dropdown exclusions
		if not self._has_dropdown_elements(context.browser_state):
			excluded.extend(self.DROPDOWN_TOOLS)

		# Navigation exclusions
		if not self._can_go_back(context):
			excluded.extend(self.NAVIGATION_TOOLS)

		# Content extraction exclusions
		if self._is_page_load_failed(context.browser_state):
			excluded.extend(self.CONTENT_TOOLS)

		# Scroll exclusions
		if not self._is_page_scrollable(context.browser_state):
			excluded.extend(self.SCROLL_TOOLS)

		return excluded

	def _apply_low_confidence_rules(self, context: ExclusionContext) -> list[str]:
		"""Apply low confidence exclusion rules (contextual exclusions)"""
		excluded = []

		# Search exclusions (avoid duplicate searches)
		if self._is_duplicate_google_search(context):
			excluded.append('search_google')

		# Wait exclusions (page already loaded)
		if self._is_page_fully_loaded(context.browser_state):
			excluded.append('wait')

		# Scroll exclusions for very short pages
		if self._is_page_too_short_to_scroll(context.browser_state):
			excluded.extend(self.SCROLL_TOOLS)

		# Extract data exclusions for PDF pages
		if context.browser_state.is_pdf_viewer:
			excluded.extend(self.CONTENT_TOOLS)

		return excluded

	def _is_google_sheets_domain(self, url: str) -> bool:
		"""Check if current URL is Google Sheets domain"""
		return url.startswith('https://docs.google.com')

	def _has_no_file_content(self, file_system: FileSystem) -> bool:
		"""Check if file system has no content (empty or only default files)"""
		if not file_system or not hasattr(file_system, 'files'):
			return True

		# Check if there are any files beyond the default todo.md
		files = file_system.files
		if not files:
			return True

		# If only todo.md exists and it's empty, consider it as no content
		if len(files) == 1 and 'todo.md' in files:
			todo_file = files['todo.md']
			if hasattr(todo_file, 'content') and not todo_file.content.strip():
				return True

		# If we have multiple files or todo.md has content, we have content
		return len(files) == 0

	def _has_clickable_elements(self, browser_state: BrowserStateSummary) -> bool:
		"""Check if page has any clickable elements"""
		if not browser_state.element_tree:
			return False

		# Check if there are any elements with interactive properties
		return self._count_interactive_elements(browser_state.element_tree) > 0

	def _count_interactive_elements(self, element_tree: Any) -> int:
		"""Count interactive elements in the DOM tree"""
		# This would need to traverse the DOM tree and count clickable elements
		# For now, we'll check if selector_map has any entries
		if hasattr(element_tree, 'children') and element_tree.children:
			return len(element_tree.children)
		return 0

	def _has_dropdown_elements(self, browser_state: BrowserStateSummary) -> bool:
		"""Check if page has dropdown elements (select, combobox, listbox)"""
		if not browser_state.element_tree:
			return False

		# Look for dropdown-related elements
		return self._find_dropdown_elements(browser_state.element_tree)

	def _find_dropdown_elements(self, element_tree: Any) -> bool:
		"""Find dropdown elements in DOM tree"""
		# This would traverse the tree looking for select, role=combobox, etc.
		# Simplified implementation for now
		if hasattr(element_tree, 'tag_name'):
			if element_tree.tag_name.lower() == 'select':
				return True
			if hasattr(element_tree, 'attributes'):
				role = element_tree.attributes.get('role', '')
				if role in ['combobox', 'listbox', 'menu']:
					return True

		if hasattr(element_tree, 'children'):
			for child in element_tree.children:
				if self._find_dropdown_elements(child):
					return True

		return False

	def _can_go_back(self, context: ExclusionContext) -> bool:
		"""Check if browser can go back (has history)"""
		# This would need browser session access to check history
		# For now, assume we can go back if we have step info and it's not step 0
		if context.step_info:
			return context.step_info.step_number > 0
		return True  # Conservative default

	def _is_page_load_failed(self, browser_state: BrowserStateSummary) -> bool:
		"""Check if page failed to load"""
		if hasattr(browser_state, 'loading_status'):
			return browser_state.loading_status == 'failed'
		return False

	def _is_page_scrollable(self, browser_state: BrowserStateSummary) -> bool:
		"""Check if page is scrollable"""
		# This would need viewport and content dimensions
		# For now, assume pages are scrollable unless very simple
		if not browser_state.element_tree:
			return False

		element_count = self._count_interactive_elements(browser_state.element_tree)
		return element_count > 5  # Simple heuristic

	def _is_duplicate_google_search(self, context: ExclusionContext) -> bool:
		"""Check if we're already on Google with the same search"""
		url = context.browser_state.url
		if 'google.com/search' in url and context.task:
			# Simple check - would need more sophisticated query comparison
			return 'search' in context.task.lower()
		return False

	def _is_page_fully_loaded(self, browser_state: BrowserStateSummary) -> bool:
		"""Check if page is fully loaded"""
		if hasattr(browser_state, 'loading_status'):
			return browser_state.loading_status == 'complete'
		return True  # Conservative default

	def _is_page_too_short_to_scroll(self, browser_state: BrowserStateSummary) -> bool:
		"""Check if page is too short to need scrolling"""
		# This would need viewport and content height comparison
		# For now, use element count as proxy
		element_count = self._count_interactive_elements(browser_state.element_tree)
		return element_count < 3  # Very simple pages probably don't need scrolling

	def get_exclusion_stats(self, context: ExclusionContext) -> dict[str, Any]:
		"""Get statistics about exclusions for debugging/monitoring"""
		excluded_tools = self.get_excluded_tools(context)

		return {
			'total_excluded': len(excluded_tools),
			'excluded_tools': excluded_tools,
			'high_confidence_exclusions': len(self._apply_high_confidence_rules(context)),
			'medium_confidence_exclusions': len(self._apply_medium_confidence_rules(context)),
			'low_confidence_exclusions': len(self._apply_low_confidence_rules(context)),
			'current_url': context.browser_state.url,
			'tab_count': len(context.browser_state.tabs),
			'has_file_system': context.file_system is not None,
			'has_file_content': not self._has_no_file_content(context.file_system) if context.file_system else False,
			'available_files': len(context.available_file_paths) if context.available_file_paths else 0,
		}
