"""Observation layer: AX-tree state for the harness-backed agent.

Cheaper cousin of browser_use.dom.service.DomService -- indexed interactive
elements from the accessibility tree instead of a full DOM snapshot.
"""

from browser_harness.sdk import Browser

from browser_use.browser.views import TabInfo
from browser_use.harness.views import HarnessElement, HarnessState

# roles the agent can act on -- containers are excluded, their contents are listed individually
INTERACTIVE_ROLES = frozenset(
	{
		'button',
		'link',
		'textbox',
		'searchbox',
		'combobox',
		'checkbox',
		'radio',
		'switch',
		'tab',
		'menuitem',
		'menuitemcheckbox',
		'menuitemradio',
		'option',
		'slider',
		'spinbutton',
		'listbox',
	}
)


class HarnessDomService:
	def __init__(self, browser: Browser, max_elements: int = 150, text_excerpt_chars: int = 6000):
		assert max_elements > 0 and text_excerpt_chars >= 0
		self.browser = browser
		self.max_elements = max_elements
		self.text_excerpt_chars = text_excerpt_chars

	async def get_state(self, include_screenshot: bool = False) -> HarnessState:
		info = await self.browser.page_info()
		if info.dialog is not None:
			# js thread is frozen -- nothing else is observable until the dialog is handled
			return HarnessState(dialog=info.dialog.model_dump())

		elements = await self._get_elements()
		text = ''
		if self.text_excerpt_chars:
			text = str(
				(await self.browser.js(f'document.body ? document.body.innerText.slice(0, {self.text_excerpt_chars}) : ""')) or ''
			)
		tabs = [
			TabInfo(url=t.url, title=t.title, target_id=t.target_id) for t in await self.browser.list_tabs(include_chrome=False)
		]
		screenshot = None
		if include_screenshot:
			# 1600px cap keeps 2x-display captures under image-aware llm limits
			screenshot = await self.browser.screenshot_b64(max_dim=1600)
		return HarnessState(
			url=info.url,
			title=info.title,
			tabs=tabs,
			elements=elements,
			text_excerpt=text,
			screenshot_b64=screenshot,
		)

	async def _get_elements(self) -> list[HarnessElement]:
		nodes = (await self.browser.cdp('Accessibility.getFullAXTree')).get('nodes', [])
		elements: list[HarnessElement] = []
		for node in nodes:
			if node.get('ignored'):
				continue
			backend_id = node.get('backendDOMNodeId')
			if backend_id is None:
				continue
			role = (node.get('role') or {}).get('value') or ''
			if role not in INTERACTIVE_ROLES:
				continue
			name = (node.get('name') or {}).get('value') or ''
			elements.append(HarnessElement(index=len(elements) + 1, role=role, name=name, backend_node_id=backend_id))
			if len(elements) >= self.max_elements:
				break
		return elements
