from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from browser_use.browser.session import BrowserSession
from browser_use.browser.views import BrowserError
from browser_use.dom.service import EnhancedDOMTreeNode


class BrowserService(BaseModel):
	"""Base class for explicit browser services."""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	browser_session: BrowserSession

	@property
	def logger(self) -> Any:
		return self.browser_session.logger

	def _default_action_watchdog(self) -> Any:
		default_action_watchdog = getattr(self.browser_session, '_default_action_watchdog', None)
		if default_action_watchdog is None:
			raise BrowserError(
				'Default action handler is not attached to this browser session. '
				'Start the BrowserSession before using click, type, or dropdown services.'
			)
		return default_action_watchdog

	async def _check_element_occlusion(self, backend_node_id: int, x: float, y: float, cdp_session) -> bool:
		"""Check if an element is occluded by other elements at the given coordinates.

		Args:
			backend_node_id: The backend node ID of the target element
			x: X coordinate to check
			y: Y coordinate to check
			cdp_session: CDP session to use

		Returns:
			True if element is occluded, False if clickable
		"""
		try:
			session_id = cdp_session.session_id

			# Get target element info for comparison
			target_result = await cdp_session.cdp_client.send.DOM.resolveNode(
				params={'backendNodeId': backend_node_id}, session_id=session_id
			)

			if 'object' not in target_result:
				self.logger.debug('Could not resolve target element, assuming occluded')
				return True

			object_id = target_result['object']['objectId']

			# Get target element info
			target_info_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
				params={
					'objectId': object_id,
					'functionDeclaration': """
					function() {
						const getElementInfo = (el) => {
							return {
								tagName: el.tagName,
								id: el.id || '',
								className: el.className || '',
								textContent: (el.textContent || '').substring(0, 100)
							};
						};


						const elementAtPoint = document.elementFromPoint(arguments[0], arguments[1]);
						if (!elementAtPoint) {
							return { targetInfo: getElementInfo(this), isClickable: false };
						}


						// Simple containment-based clickability logic
						let isClickable = this === elementAtPoint ||
							this.contains(elementAtPoint) ||
							elementAtPoint.contains(this);

						// Check label-input associations when containment check fails
						if (!isClickable) {
							const target = this;
							const atPoint = elementAtPoint;

							// Case 1: target is <input>, atPoint is its associated <label> (or child of that label)
							if (target.tagName === 'INPUT' && target.id) {
								const escapedId = CSS.escape(target.id);
								const assocLabel = document.querySelector('label[for="' + escapedId + '"]');
								if (assocLabel && (assocLabel === atPoint || assocLabel.contains(atPoint))) {
									isClickable = true;
								}
							}

							// Case 2: target is <input>, atPoint is inside a <label> ancestor that wraps the target
							if (!isClickable && target.tagName === 'INPUT') {
								let ancestor = atPoint;
								for (let i = 0; i < 3 && ancestor; i++) {
									if (ancestor.tagName === 'LABEL' && ancestor.contains(target)) {
										isClickable = true;
										break;
									}
									ancestor = ancestor.parentElement;
								}
							}

							// Case 3: target is <label>, atPoint is the associated <input>
							if (!isClickable && target.tagName === 'LABEL') {
								if (target.htmlFor && atPoint.tagName === 'INPUT' && atPoint.id === target.htmlFor) {
									isClickable = true;
								}
								// Also check if atPoint is an input inside the label
								if (!isClickable && atPoint.tagName === 'INPUT' && target.contains(atPoint)) {
									isClickable = true;
								}
							}
						}

						return {
							targetInfo: getElementInfo(this),
							elementAtPointInfo: getElementInfo(elementAtPoint),
							isClickable: isClickable
						};
					}
					""",
					'arguments': [{'value': x}, {'value': y}],
					'returnByValue': True,
				},
				session_id=session_id,
			)

			if 'result' not in target_info_result or 'value' not in target_info_result['result']:
				self.logger.debug('Could not get target element info, assuming occluded')
				return True

			target_data = target_info_result['result']['value']
			is_clickable = target_data.get('isClickable', False)

			if is_clickable:
				self.logger.debug('Element is clickable (target, contained, or semantically related)')
				return False
			else:
				target_info = target_data.get('targetInfo', {})
				element_at_point_info = target_data.get('elementAtPointInfo', {})
				self.logger.debug(
					f'Element is occluded. Target: {target_info.get("tagName", "unknown")} '
					f'(id={target_info.get("id", "none")}), '
					f'ElementAtPoint: {element_at_point_info.get("tagName", "unknown")} '
					f'(id={element_at_point_info.get("id", "none")})'
				)
				return True

		except Exception as e:
			self.logger.debug(f'Occlusion check failed: {e}, assuming not occluded')
			return False

	async def _get_session_id_for_element(self, element_node: EnhancedDOMTreeNode) -> str | None:
		"""Get the appropriate CDP session ID for an element based on its frame."""
		if element_node.frame_id:
			# Element is in an iframe, need to get session for that frame
			try:
				all_targets = self.browser_session.session_manager.get_all_targets()

				# Find the target for this frame
				for target_id, target in all_targets.items():
					if target.target_type == 'iframe' and element_node.frame_id in str(target_id):
						# Create temporary session for iframe target without switching focus
						temp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)
						return temp_session.session_id

				# If frame not found in targets, use main target session
				self.logger.debug(f'Frame {element_node.frame_id} not found in targets, using main session')
			except Exception as e:
				self.logger.debug(f'Error getting frame session: {e}, using main session')

		# Use main target session - get_or_create_cdp_session validates focus automatically
		cdp_session = await self.browser_session.get_or_create_cdp_session()
		return cdp_session.session_id
