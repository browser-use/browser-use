"""Tab, target, and DOM compatibility helpers for BrowserSession."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from cdp_use.cdp.target import TargetID

from browser_use.browser.events import NavigateToUrlEvent
from browser_use.browser.views import TabInfo
from browser_use.dom.views import EnhancedDOMTreeNode, NodeType, TargetInfo
from browser_use.utils import _log_pretty_url, is_new_tab_page


class BrowserSessionDOMMixin:
	"""Tab metadata, selector-map, and DOM lookup helpers."""

	async def get_tabs(self: Any) -> list[TabInfo]:
		"""Get information about all open tabs using cached target data."""
		tabs = []

		if not self.session_manager:
			return tabs

		page_targets = self.session_manager.get_all_page_targets()

		for i, target in enumerate(page_targets):
			target_id = target.target_id
			url = target.url
			title = target.title

			try:
				if is_new_tab_page(url) or url.startswith('chrome://'):
					if is_new_tab_page(url):
						title = ''
					elif not title:
						title = url

				if (not title or title == '') and (url.endswith('.pdf') or 'pdf' in url):
					try:
						filename = urlparse(url).path.split('/')[-1]
						if filename:
							title = filename
					except Exception:
						pass

			except Exception as e:
				self.logger.debug(f'Failed to get target info for tab #{i}: {_log_pretty_url(url)} - {type(e).__name__}')

				if is_new_tab_page(url):
					title = ''
				elif url.startswith('chrome://'):
					title = url
				else:
					title = ''

			tabs.append(
				TabInfo(
					target_id=target_id,
					url=url,
					title=title,
					parent_target_id=None,
				)
			)

		return tabs

	async def get_current_target_info(self: Any) -> TargetInfo | None:
		"""Get info about the current active target using cached session data."""
		if not self.agent_focus_target_id:
			return None

		target = self.session_manager.get_target(self.agent_focus_target_id)

		return {
			'targetId': target.target_id,
			'url': target.url,
			'title': target.title,
			'type': target.target_type,
			'attached': True,
			'canAccessOpener': False,
		}

	async def get_current_page_url(self: Any) -> str:
		"""Get the URL of the current page."""
		if self.agent_focus_target_id:
			target = self.session_manager.get_target(self.agent_focus_target_id)
			return target.url
		return 'about:blank'

	async def get_current_page_title(self: Any) -> str:
		"""Get the title of the current page."""
		if self.agent_focus_target_id:
			target = self.session_manager.get_target(self.agent_focus_target_id)
			return target.title
		return 'Unknown page title'

	async def navigate_to(self: Any, url: str, new_tab: bool = False) -> None:
		"""Navigate to a URL using the standard event system."""
		event = self.event_bus.dispatch(NavigateToUrlEvent(url=url, new_tab=new_tab))
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)

	async def get_dom_element_by_index(self: Any, index: int) -> EnhancedDOMTreeNode | None:
		"""Get DOM element by index from the cached selector map."""
		if self._cached_selector_map and index in self._cached_selector_map:
			return self._cached_selector_map[index]

		return None

	def update_cached_selector_map(self: Any, selector_map: dict[int, EnhancedDOMTreeNode]) -> None:
		"""Update the cached selector map with new DOM state."""
		self._cached_selector_map = selector_map

	async def get_element_by_index(self: Any, index: int) -> EnhancedDOMTreeNode | None:
		"""Alias for get_dom_element_by_index for backwards compatibility."""
		return await self.get_dom_element_by_index(index)

	async def get_dom_element_at_coordinates(self: Any, x: int, y: int) -> EnhancedDOMTreeNode | None:
		"""Get DOM element at coordinates as EnhancedDOMTreeNode."""
		page = await self.get_current_page()
		if page is None:
			raise RuntimeError('No active page found')

		session_id = await page._ensure_session()

		try:
			result = await self.cdp_client.send.DOM.getNodeForLocation(
				params={
					'x': x,
					'y': y,
					'includeUserAgentShadowDOM': False,
					'ignorePointerEventsNone': False,
				},
				session_id=session_id,
			)

			backend_node_id = result.get('backendNodeId')
			if backend_node_id is None:
				self.logger.debug(f'No element found at coordinates ({x}, {y})')
				return None

			if self._cached_selector_map:
				for node in self._cached_selector_map.values():
					if node.backend_node_id == backend_node_id:
						self.logger.debug(f'Found element at ({x}, {y}) in cached selector_map')
						return node

			try:
				describe_result = await self.cdp_client.send.DOM.describeNode(
					params={'backendNodeId': backend_node_id},
					session_id=session_id,
				)
				node_info = describe_result.get('node', {})
				node_name = node_info.get('nodeName', '')

				attrs_list = node_info.get('attributes', [])
				attributes = {attrs_list[i]: attrs_list[i + 1] for i in range(0, len(attrs_list), 2)}

				return EnhancedDOMTreeNode(
					node_id=result.get('nodeId', 0),
					backend_node_id=backend_node_id,
					node_type=NodeType(node_info.get('nodeType', NodeType.ELEMENT_NODE.value)),
					node_name=node_name,
					node_value=node_info.get('nodeValue', '') or '',
					attributes=attributes,
					is_scrollable=None,
					frame_id=result.get('frameId'),
					session_id=session_id,
					target_id=self.agent_focus_target_id or '',
					content_document=None,
					shadow_root_type=None,
					shadow_roots=None,
					parent_node=None,
					children_nodes=None,
					ax_node=None,
					snapshot_node=None,
					is_visible=None,
					absolute_position=None,
				)
			except Exception as e:
				self.logger.debug(f'DOM.describeNode failed for backend_node_id={backend_node_id}: {e}')
				return EnhancedDOMTreeNode(
					node_id=result.get('nodeId', 0),
					backend_node_id=backend_node_id,
					node_type=NodeType.ELEMENT_NODE,
					node_name='',
					node_value='',
					attributes={},
					is_scrollable=None,
					frame_id=result.get('frameId'),
					session_id=session_id,
					target_id=self.agent_focus_target_id or '',
					content_document=None,
					shadow_root_type=None,
					shadow_roots=None,
					parent_node=None,
					children_nodes=None,
					ax_node=None,
					snapshot_node=None,
					is_visible=None,
					absolute_position=None,
				)

		except Exception as e:
			self.logger.warning(f'Failed to get DOM element at coordinates ({x}, {y}): {e}')
			return None

	async def get_target_id_from_tab_id(self: Any, tab_id: str) -> TargetID:
		"""Get the full-length TargetID from the truncated 4-char tab_id."""
		if not self.session_manager:
			raise RuntimeError('SessionManager not initialized')

		for full_target_id in self.session_manager.get_all_target_ids():
			if full_target_id.endswith(tab_id):
				if await self.session_manager.is_target_valid(full_target_id):
					return full_target_id
				self.logger.debug(f'Found stale target {full_target_id}, skipping')

		raise ValueError(f'No TargetID found ending in tab_id=...{tab_id}')

	async def get_target_id_from_url(self: Any, url: str) -> TargetID:
		"""Get the TargetID from a URL using SessionManager."""
		if not self.session_manager:
			raise RuntimeError('SessionManager not initialized')

		for target_id, target in self.session_manager.get_all_targets().items():
			if target.target_type in ('page', 'tab') and target.url == url:
				return target_id

		for target_id, target in self.session_manager.get_all_targets().items():
			if target.target_type in ('page', 'tab') and url in target.url:
				return target_id

		raise ValueError(f'No TargetID found for url={url}')

	async def get_most_recently_opened_target_id(self: Any) -> TargetID:
		"""Get the most recently opened target ID using SessionManager."""
		page_targets = self.session_manager.get_all_page_targets()
		if not page_targets:
			raise RuntimeError('No page targets available')
		return page_targets[-1].target_id

	def is_file_input(self: Any, element: Any) -> bool:
		"""Check if element is a file input."""
		if self._dom_watchdog:
			return self._dom_watchdog.is_file_input(element)
		return (
			hasattr(element, 'node_name')
			and element.node_name.upper() == 'INPUT'
			and hasattr(element, 'attributes')
			and element.attributes.get('type', '').lower() == 'file'
		)

	def find_file_input_near_element(
		self: Any,
		node: EnhancedDOMTreeNode,
		max_height: int = 3,
		max_descendant_depth: int = 3,
	) -> EnhancedDOMTreeNode | None:
		"""Find the closest file input to the given element."""

		def _find_in_descendants(n: EnhancedDOMTreeNode, depth: int) -> EnhancedDOMTreeNode | None:
			if depth < 0:
				return None
			if self.is_file_input(n):
				return n
			for child in n.children_nodes or []:
				result = _find_in_descendants(child, depth - 1)
				if result:
					return result
			return None

		current: EnhancedDOMTreeNode | None = node
		for _ in range(max_height + 1):
			if current is None:
				break
			if self.is_file_input(current):
				return current
			result = _find_in_descendants(current, max_descendant_depth)
			if result:
				return result
			if current.parent_node:
				for sibling in current.parent_node.children_nodes or []:
					if sibling is current:
						continue
					if self.is_file_input(sibling):
						return sibling
					result = _find_in_descendants(sibling, max_descendant_depth)
					if result:
						return result
			current = current.parent_node
		return None

	async def get_selector_map(self: Any) -> dict[int, EnhancedDOMTreeNode]:
		"""Get the current selector map from cached state or DOM watchdog."""
		if self._cached_selector_map:
			return self._cached_selector_map

		if self._dom_watchdog and hasattr(self._dom_watchdog, 'selector_map'):
			return self._dom_watchdog.selector_map or {}

		return {}

	async def get_index_by_id(self: Any, element_id: str) -> int | None:
		"""Find element index by its id attribute."""
		selector_map = await self.get_selector_map()
		for idx, element in selector_map.items():
			if element.attributes and element.attributes.get('id') == element_id:
				return idx
		return None

	async def get_index_by_class(self: Any, class_name: str) -> int | None:
		"""Find element index by its class attribute."""
		selector_map = await self.get_selector_map()
		for idx, element in selector_map.items():
			if element.attributes:
				element_class = element.attributes.get('class', '')
				if class_name in element_class.split():
					return idx
		return None
