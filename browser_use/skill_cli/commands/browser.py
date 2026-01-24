"""Browser control commands."""

import base64
import logging
from pathlib import Path
from typing import Any

from browser_use.skill_cli.sessions import SessionInfo

logger = logging.getLogger(__name__)

COMMANDS = {
	'open',
	'click',
	'type',
	'input',
	'scroll',
	'back',
	'screenshot',
	'state',
	'switch',
	'close-tab',
	'keys',
	'select',
	'eval',
	'extract',
}


async def _execute_js(session: SessionInfo, js: str) -> Any:
	"""Execute JavaScript in the browser via CDP."""
	bs = session.browser_session
	# Get or create a CDP session for the focused target
	cdp_session = await bs.get_or_create_cdp_session(target_id=None, focus=False)
	if not cdp_session:
		raise RuntimeError('No active browser session')

	result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': js, 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	return result.get('result', {}).get('value')


async def handle(action: str, session: SessionInfo, params: dict[str, Any]) -> Any:
	"""Handle browser control command."""
	bs = session.browser_session

	if action == 'open':
		url = params['url']
		# Ensure URL has scheme
		if not url.startswith(('http://', 'https://', 'file://')):
			url = 'https://' + url

		from browser_use.browser.events import NavigateToUrlEvent

		await bs.event_bus.dispatch(NavigateToUrlEvent(url=url))
		result: dict[str, Any] = {'url': url}
		# Add live preview URL for cloud browsers
		if bs.browser_profile.use_cloud and bs.cdp_url:
			from urllib.parse import quote

			result['live_url'] = f'https://live.browser-use.com/?wss={quote(bs.cdp_url, safe="")}'
		return result

	elif action == 'click':
		from browser_use.browser.events import ClickElementEvent

		index = params['index']
		# Look up node from selector map
		node = await bs.get_element_by_index(index)
		if node is None:
			return {'error': f'Element index {index} not found - page may have changed'}
		await bs.event_bus.dispatch(ClickElementEvent(node=node))
		return {'clicked': index}

	elif action == 'type':
		# Type into currently focused element using CDP directly
		text = params['text']
		cdp_session = await bs.get_or_create_cdp_session(target_id=None, focus=False)
		if not cdp_session:
			return {'error': 'No active browser session'}
		await cdp_session.cdp_client.send.Input.insertText(
			params={'text': text},
			session_id=cdp_session.session_id,
		)
		return {'typed': text}

	elif action == 'input':
		from browser_use.browser.events import ClickElementEvent, TypeTextEvent

		index = params['index']
		text = params['text']
		# Look up node from selector map
		node = await bs.get_element_by_index(index)
		if node is None:
			return {'error': f'Element index {index} not found - page may have changed'}
		await bs.event_bus.dispatch(ClickElementEvent(node=node))
		await bs.event_bus.dispatch(TypeTextEvent(node=node, text=text))
		return {'input': text, 'element': index}

	elif action == 'scroll':
		from browser_use.browser.events import ScrollEvent

		direction = params.get('direction', 'down')
		amount = params.get('amount', 500)
		await bs.event_bus.dispatch(ScrollEvent(direction=direction, amount=amount))
		return {'scrolled': direction, 'amount': amount}

	elif action == 'back':
		from browser_use.browser.events import GoBackEvent

		await bs.event_bus.dispatch(GoBackEvent())
		return {'back': True}

	elif action == 'screenshot':
		data = await bs.take_screenshot(full_page=params.get('full', False))

		if params.get('path'):
			path = Path(params['path'])
			path.write_bytes(data)
			return {'saved': str(path), 'size': len(data)}

		# Return base64 encoded
		return {'screenshot': base64.b64encode(data).decode(), 'size': len(data)}

	elif action == 'state':
		# Return the same LLM representation that browser-use agents see
		state_text = await bs.get_state_as_text()
		return {'_raw_text': state_text}

	elif action == 'switch':
		from browser_use.browser.events import SwitchTabEvent

		tab_index = params['tab']
		# Get target_id from tab index
		page_targets = bs.session_manager.get_all_page_targets() if bs.session_manager else []
		if tab_index < 0 or tab_index >= len(page_targets):
			return {'error': f'Invalid tab index {tab_index}. Available: 0-{len(page_targets) - 1}'}
		target_id = page_targets[tab_index].target_id
		await bs.event_bus.dispatch(SwitchTabEvent(target_id=target_id))
		return {'switched': tab_index}

	elif action == 'close-tab':
		from browser_use.browser.events import CloseTabEvent

		tab_index = params.get('tab')
		# Get target_id from tab index
		page_targets = bs.session_manager.get_all_page_targets() if bs.session_manager else []
		if tab_index is not None:
			if tab_index < 0 or tab_index >= len(page_targets):
				return {'error': f'Invalid tab index {tab_index}. Available: 0-{len(page_targets) - 1}'}
			target_id = page_targets[tab_index].target_id
		else:
			# Close current/focused tab
			target_id = bs.session_manager.get_focused_target().target_id if bs.session_manager else None
			if not target_id:
				return {'error': 'No focused tab to close'}
		await bs.event_bus.dispatch(CloseTabEvent(target_id=target_id))
		return {'closed': tab_index}

	elif action == 'keys':
		from browser_use.browser.events import SendKeysEvent

		keys = params['keys']
		await bs.event_bus.dispatch(SendKeysEvent(keys=keys))
		return {'sent': keys}

	elif action == 'select':
		from browser_use.browser.events import SelectDropdownOptionEvent

		index = params['index']
		value = params['value']
		# Look up node from selector map
		node = await bs.get_element_by_index(index)
		if node is None:
			return {'error': f'Element index {index} not found - page may have changed'}
		await bs.event_bus.dispatch(SelectDropdownOptionEvent(node=node, text=value))
		return {'selected': value, 'element': index}

	elif action == 'eval':
		js = params['js']
		# Execute JavaScript via CDP
		result = await _execute_js(session, js)
		return {'result': result}

	elif action == 'extract':
		query = params['query']
		# This requires LLM integration
		# For now, return a placeholder
		return {'query': query, 'error': 'extract requires agent mode - use: browser-use run "extract ..."'}

	raise ValueError(f'Unknown browser action: {action}')
