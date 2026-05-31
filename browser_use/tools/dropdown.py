import logging

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.services import BrowserServiceBundle
from browser_use.tools.views import GetDropdownOptionsAction, SelectDropdownOptionAction

logger = logging.getLogger(__name__)


async def dropdown_options_action(params: GetDropdownOptionsAction, browser_session: BrowserSession) -> ActionResult:
	"""Get all options from a native dropdown or ARIA menu."""
	node = await browser_session.get_element_by_index(params.index)
	if node is None:
		msg = f'Element index {params.index} not available - page may have changed. Try refreshing browser state.'
		logger.warning(f'⚠️ {msg}')
		return ActionResult(extracted_content=msg)

	dropdown_data = await BrowserServiceBundle.from_session(browser_session).actions.dropdown.get_options(node)

	if not dropdown_data:
		raise ValueError('Failed to get dropdown options - no data returned')

	return ActionResult(
		extracted_content=dropdown_data['short_term_memory'],
		long_term_memory=dropdown_data['long_term_memory'],
		include_extracted_content_only_once=True,
	)


async def select_dropdown_action(params: SelectDropdownOptionAction, browser_session: BrowserSession) -> ActionResult:
	"""Select dropdown option by the text of the option you want to select."""
	node = await browser_session.get_element_by_index(params.index)
	if node is None:
		msg = f'Element index {params.index} not available - page may have changed. Try refreshing browser state.'
		logger.warning(f'⚠️ {msg}')
		return ActionResult(extracted_content=msg)

	selection_data = await BrowserServiceBundle.from_session(browser_session).actions.dropdown.select_option(node, params.text)

	if not selection_data:
		raise ValueError('Failed to select dropdown option - no data returned')

	if selection_data.get('success') == 'true':
		msg = selection_data.get('message', f'Selected option: {params.text}')
		return ActionResult(
			extracted_content=msg,
			include_in_memory=True,
			long_term_memory=f"Selected dropdown option '{params.text}' at index {params.index}",
		)

	if 'short_term_memory' in selection_data and 'long_term_memory' in selection_data:
		return ActionResult(
			extracted_content=selection_data['short_term_memory'],
			long_term_memory=selection_data['long_term_memory'],
			include_extracted_content_only_once=True,
		)

	error_msg = selection_data.get('error', f'Failed to select option: {params.text}')
	return ActionResult(error=error_msg)
