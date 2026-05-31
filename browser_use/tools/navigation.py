import asyncio
import logging
import urllib.parse

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.services import BrowserServiceBundle
from browser_use.tools.views import CloseTabAction, NavigateAction, SearchAction, SendKeysAction, SwitchTabAction, WaitAction

logger = logging.getLogger(__name__)


async def search_action(params: SearchAction, browser_session: BrowserSession) -> ActionResult:
	"""Navigate to a search-engine results page for the query."""
	encoded_query = urllib.parse.quote_plus(params.query)
	search_engines = {
		'duckduckgo': f'https://duckduckgo.com/?q={encoded_query}',
		'google': f'https://www.google.com/search?q={encoded_query}&udm=14',
		'bing': f'https://www.bing.com/search?q={encoded_query}',
	}

	if params.engine.lower() not in search_engines:
		return ActionResult(error=f'Unsupported search engine: {params.engine}. Options: duckduckgo, google, bing')

	try:
		await BrowserServiceBundle.from_session(browser_session).navigation.navigate(
			search_engines[params.engine.lower()], new_tab=False
		)
		memory = f"Searched {params.engine.title()} for '{params.query}'"
		logger.info(f'🔍  {memory}')
		return ActionResult(extracted_content=memory, long_term_memory=memory)
	except Exception as e:
		logger.error(f'Failed to search {params.engine}: {e}')
		return ActionResult(error=f'Failed to search {params.engine} for "{params.query}": {str(e)}')


async def navigate_action(params: NavigateAction, browser_session: BrowserSession) -> ActionResult:
	"""Navigate the active tab, or open a new tab, through direct browser services."""
	try:
		await BrowserServiceBundle.from_session(browser_session).navigation.navigate(params.url, new_tab=params.new_tab)

		if params.new_tab:
			memory = f'Opened new tab with URL {params.url}'
			msg = f'🔗  Opened new tab with url {params.url}'
		else:
			memory = f'Navigated to {params.url}'
			msg = f'🔗 {memory}'

		logger.info(msg)
		return ActionResult(extracted_content=msg, long_term_memory=memory)
	except Exception as e:
		error_msg = str(e)
		browser_session.logger.error(f'❌ Navigation failed: {error_msg}')

		if isinstance(e, RuntimeError) and 'CDP client not initialized' in error_msg:
			browser_session.logger.error('❌ Browser connection failed - CDP client not properly initialized')
			return ActionResult(error=f'Browser connection error: {error_msg}')
		if any(
			err in error_msg
			for err in [
				'ERR_NAME_NOT_RESOLVED',
				'ERR_INTERNET_DISCONNECTED',
				'ERR_CONNECTION_REFUSED',
				'ERR_TIMED_OUT',
				'ERR_TUNNEL_CONNECTION_FAILED',
				'net::',
			]
		):
			site_unavailable_msg = f'Navigation failed - site unavailable: {params.url}'
			browser_session.logger.warning(f'⚠️ {site_unavailable_msg} - {error_msg}')
			return ActionResult(error=site_unavailable_msg)

		return ActionResult(error=f'Navigation failed: {str(e)}')


async def go_back_action(browser_session: BrowserSession) -> ActionResult:
	"""Navigate back through direct browser services."""
	try:
		await BrowserServiceBundle.from_session(browser_session).navigation.go_back()
		memory = 'Navigated back'
		logger.info(f'🔙  {memory}')
		return ActionResult(extracted_content=memory)
	except Exception as e:
		logger.error(f'Failed to go back through direct browser service: {type(e).__name__}: {e}')
		return ActionResult(error=f'Failed to go back: {str(e)}')


async def wait_action(params: WaitAction) -> ActionResult:
	"""Wait for a bounded number of seconds."""
	seconds = params.seconds
	actual_seconds = min(max(seconds - 1, 0), 30)
	memory = f'Waited for {seconds} seconds'
	logger.info(f'🕒 waited for {seconds} second{"" if seconds == 1 else "s"}')
	await asyncio.sleep(actual_seconds)
	return ActionResult(extracted_content=memory, long_term_memory=memory)


async def send_keys_action(params: SendKeysAction, browser_session: BrowserSession) -> ActionResult:
	"""Send keyboard input through direct browser services."""
	try:
		await BrowserServiceBundle.from_session(browser_session).actions.keyboard.send_keys(params.keys)
		memory = f'Sent keys: {params.keys}'
		logger.info(f'⌨️  {memory}')
		return ActionResult(extracted_content=memory, long_term_memory=memory)
	except Exception as e:
		logger.error(f'Failed to send keys through direct browser service: {type(e).__name__}: {e}')
		return ActionResult(error=f'Failed to send keys: {str(e)}')


async def switch_tab_action(params: SwitchTabAction, browser_session: BrowserSession) -> ActionResult:
	"""Switch to a tab by short tab id."""
	try:
		target_id = await browser_session.get_target_id_from_tab_id(params.tab_id)
		new_target_id = await BrowserServiceBundle.from_session(browser_session).tabs.switch(target_id)

		if new_target_id:
			memory = f'Switched to tab #{new_target_id[-4:]}'
		else:
			memory = f'Switched to tab #{params.tab_id}'

		logger.info(f'🔄  {memory}')
		return ActionResult(extracted_content=memory, long_term_memory=memory)
	except Exception as e:
		logger.warning(f'Tab switch may have failed: {e}')
		memory = f'Attempted to switch to tab #{params.tab_id}'
		return ActionResult(extracted_content=memory, long_term_memory=memory)


async def close_tab_action(params: CloseTabAction, browser_session: BrowserSession) -> ActionResult:
	"""Close a tab by short tab id."""
	try:
		target_id = await browser_session.get_target_id_from_tab_id(params.tab_id)
		await BrowserServiceBundle.from_session(browser_session).tabs.close(target_id)

		memory = f'Closed tab #{params.tab_id}'
		logger.info(f'🗑️  {memory}')
		return ActionResult(extracted_content=memory, long_term_memory=memory)
	except Exception as e:
		logger.warning(f'Tab {params.tab_id} may already be closed: {e}')
		memory = f'Tab #{params.tab_id} closed (was already closed or invalid)'
		return ActionResult(extracted_content=memory, long_term_memory=memory)
