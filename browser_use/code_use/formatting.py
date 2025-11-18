"""Browser state formatting helpers for code-use agent."""

import logging
from typing import Any

from browser_use.browser.session import BrowserSession
from browser_use.browser.views import BrowserStateSummary

logger = logging.getLogger(__name__)


async def format_browser_state_for_llm(
	state: BrowserStateSummary,
	namespace: dict[str, Any],
	browser_session: BrowserSession,
) -> str:
	"""
	Format browser state summary for LLM consumption in code-use mode.

	Args:
		state: Browser state summary from browser_session.get_browser_state_summary()
		namespace: The code execution namespace (for showing available variables)
		browser_session: Browser session for additional checks (jQuery, etc.)

	Returns:
		Formatted browser state text for LLM
	"""
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

	# Add network loading info if there are pending requests
	if state.pending_network_requests:
		# Remove duplicates by URL (keep first occurrence with earliest duration)
		seen_urls = set()
		unique_requests = []
		for req in state.pending_network_requests:
			if req.url not in seen_urls:
				seen_urls.add(req.url)
				unique_requests.append(req)

		lines.append(f'**⏳ Loading:** {len(unique_requests)} network requests still loading')
		# Show up to 20 unique requests with truncated URLs (30 chars max)
		for req in unique_requests[:20]:
			duration_sec = req.loading_duration_ms / 1000
			url_display = req.url if len(req.url) <= 30 else req.url[:27] + '...'
			logger.info(f'  - [{duration_sec:.1f}s] {url_display}')
			lines.append(f'  - [{duration_sec:.1f}s] {url_display}')
		if len(unique_requests) > 20:
			lines.append(f'  - ... and {len(unique_requests) - 20} more')
		lines.append('**Tip:** Content may still be loading. Consider waiting with `await asyncio.sleep(1)` if data is missing.')
		lines.append('')

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
	tracked_code_blocks = namespace.get('_code_block_vars', set())
	for name in namespace.keys():
		# Skip private vars and system objects/actions
		if not name.startswith('_') and name not in skip_vars:
			if name in tracked_code_blocks:
				code_block_vars.append(name)
			else:
				regular_vars.append(name)

	# Sort for consistent display
	available_vars_sorted = sorted(regular_vars)
	code_block_vars_sorted = sorted(code_block_vars)

	# Build available line with code blocks and variables
	parts = []
	if code_block_vars_sorted:
		# Show detailed info for code block variables
		code_block_details = []
		for var_name in code_block_vars_sorted:
			value = namespace.get(var_name)
			if value is not None:
				type_name = type(value).__name__
				value_str = str(value) if not isinstance(value, str) else value

				# Check if it's a function (starts with "(function" or "(async function")
				is_function = value_str.strip().startswith('(function') or value_str.strip().startswith('(async function')

				if is_function:
					# For functions, only show name and type
					detail = f'{var_name}({type_name})'
				else:
					# For non-functions, show first and last 20 chars
					first_20 = value_str[:20].replace('\n', '\\n').replace('\t', '\\t')
					last_20 = value_str[-20:].replace('\n', '\\n').replace('\t', '\\t') if len(value_str) > 20 else ''

					if last_20 and first_20 != last_20:
						detail = f'{var_name}({type_name}): "{first_20}...{last_20}"'
					else:
						detail = f'{var_name}({type_name}): "{first_20}"'
				code_block_details.append(detail)

		parts.append(f'**Code block variables:** {" | ".join(code_block_details)}')
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
	return browser_state_text
