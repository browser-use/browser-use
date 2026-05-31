"""Frame and target session resolution helpers for BrowserSession."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cdp_use.cdp.target import TargetID

if TYPE_CHECKING:
	from browser_use.browser.session import CDPSession
	from browser_use.dom.views import EnhancedDOMTreeNode


class BrowserSessionFramesMixin:
	"""Resolve browser frames, targets, and CDP sessions."""

	async def get_all_frames(self: Any) -> tuple[dict[str, dict], dict[str, str]]:
		"""Get a complete frame hierarchy from all browser targets."""
		all_frames = {}
		target_sessions = {}

		include_cross_origin = self.browser_profile.cross_origin_iframes

		targets = await self._cdp_get_all_pages(
			include_http=True,
			include_about=True,
			include_pages=True,
			include_iframes=include_cross_origin,
			include_workers=False,
			include_chrome=False,
			include_chrome_extensions=False,
			include_chrome_error=include_cross_origin,
		)

		for target in targets:
			target_id = target['targetId']

			if not include_cross_origin and target.get('type') == 'iframe':
				continue

			if not include_cross_origin:
				if self.agent_focus_target_id and target_id != self.agent_focus_target_id:
					continue
				try:
					cdp_session = await self.get_or_create_cdp_session(self.agent_focus_target_id, focus=False)
				except ValueError:
					continue
			else:
				try:
					cdp_session = await self.get_or_create_cdp_session(target_id, focus=False)
				except ValueError:
					continue

			if cdp_session:
				target_sessions[target_id] = cdp_session.session_id

				try:
					frame_tree_result = await cdp_session.cdp_client.send.Page.getFrameTree(session_id=cdp_session.session_id)

					def process_frame_tree(node: dict[str, Any], parent_frame_id: str | None = None) -> None:
						frame = node.get('frame', {})
						current_frame_id = frame.get('id')

						if current_frame_id:
							actual_parent_id = frame.get('parentId') or parent_frame_id

							frame_info = {
								**frame,
								'frameTargetId': target_id,
								'parentFrameId': actual_parent_id,
								'childFrameIds': [],
								'isCrossOrigin': False,
								'isValidTarget': self._is_valid_target(
									target,
									include_http=True,
									include_about=True,
									include_pages=True,
									include_iframes=True,
									include_workers=False,
									include_chrome=False,
									include_chrome_extensions=False,
									include_chrome_error=False,
								),
							}

							cross_origin_type = frame.get('crossOriginIsolatedContextType')
							if cross_origin_type and cross_origin_type != 'NotIsolated':
								frame_info['isCrossOrigin'] = True

							if target.get('type') == 'iframe':
								frame_info['isCrossOrigin'] = True

							if not include_cross_origin and frame_info.get('isCrossOrigin'):
								return

							child_frames = node.get('childFrames', [])
							for child in child_frames:
								child_frame = child.get('frame', {})
								child_frame_id = child_frame.get('id')
								if child_frame_id:
									frame_info['childFrameIds'].append(child_frame_id)

							if current_frame_id in all_frames:
								existing = all_frames[current_frame_id]
								if target.get('type') == 'iframe':
									existing['frameTargetId'] = target_id
									existing['isCrossOrigin'] = True
							else:
								all_frames[current_frame_id] = frame_info

							if include_cross_origin or not frame_info.get('isCrossOrigin'):
								for child in child_frames:
									process_frame_tree(child, current_frame_id)

					process_frame_tree(frame_tree_result.get('frameTree', {}))

				except Exception as e:
					self.logger.debug(f'Failed to get frame tree for target {target_id}: {e}')

		if include_cross_origin:
			await self._populate_frame_metadata(all_frames, target_sessions)

		return all_frames, target_sessions

	async def _populate_frame_metadata(self: Any, all_frames: dict[str, dict], target_sessions: dict[str, str]) -> None:
		"""Populate additional frame metadata like backend node IDs and parent target IDs."""
		for frame_id_iter, frame_info in all_frames.items():
			parent_frame_id = frame_info.get('parentFrameId')

			if parent_frame_id and parent_frame_id in all_frames:
				parent_frame_info = all_frames[parent_frame_id]
				parent_target_id = parent_frame_info.get('frameTargetId')

				frame_info['parentTargetId'] = parent_target_id

				if parent_target_id in target_sessions:
					assert parent_target_id is not None
					parent_session_id = target_sessions[parent_target_id]
					try:
						await self.cdp_client.send.DOM.enable(session_id=parent_session_id)

						frame_owner = await self.cdp_client.send.DOM.getFrameOwner(
							params={'frameId': frame_id_iter}, session_id=parent_session_id
						)

						if frame_owner:
							frame_info['backendNodeId'] = frame_owner.get('backendNodeId')
							frame_info['nodeId'] = frame_owner.get('nodeId')

					except Exception:
						pass

	async def find_frame_target(self: Any, frame_id: str, all_frames: dict[str, dict] | None = None) -> dict | None:
		"""Find the frame info for a specific frame ID."""
		frame_map = all_frames
		if frame_map is None:
			frame_map, _ = await self.get_all_frames()

		return frame_map.get(frame_id)

	async def cdp_client_for_target(self: Any, target_id: TargetID) -> CDPSession:
		"""Get a CDP session for a target without changing focus."""
		return await self.get_or_create_cdp_session(target_id, focus=False)

	async def cdp_client_for_frame(self: Any, frame_id: str) -> CDPSession:
		"""Get a CDP session attached to the target containing a frame."""
		if not self.browser_profile.cross_origin_iframes:
			return await self.get_or_create_cdp_session()

		all_frames, target_sessions = await self.get_all_frames()
		frame_info = await self.find_frame_target(frame_id, all_frames)

		if frame_info:
			target_id = frame_info.get('frameTargetId')

			if target_id in target_sessions:
				assert target_id is not None
				return await self.get_or_create_cdp_session(target_id, focus=False)

		raise ValueError(f"Frame with ID '{frame_id}' not found in any target")

	async def cdp_client_for_node(self: Any, node: EnhancedDOMTreeNode) -> CDPSession:
		"""Get CDP client for a DOM node based on its captured session, frame, or target."""
		if node.session_id and self.session_manager:
			try:
				cdp_session = self.session_manager.get_session(node.session_id)
				if cdp_session:
					target = self.session_manager.get_target(cdp_session.target_id)
					self.logger.debug(f'Using session from node.session_id for node {node.backend_node_id}: {target.url}')
					return cdp_session
			except Exception as e:
				self.logger.debug(f'Failed to get session by session_id {node.session_id}: {e}')

		if node.frame_id:
			try:
				cdp_session = await self.cdp_client_for_frame(node.frame_id)
				target = self.session_manager.get_target(cdp_session.target_id)
				self.logger.debug(f'Using session from node.frame_id for node {node.backend_node_id}: {target.url}')
				return cdp_session
			except Exception as e:
				self.logger.debug(f'Failed to get session for frame {node.frame_id}: {e}')

		if node.target_id:
			try:
				cdp_session = await self.get_or_create_cdp_session(target_id=node.target_id, focus=False)
				target = self.session_manager.get_target(cdp_session.target_id)
				self.logger.debug(f'Using session from node.target_id for node {node.backend_node_id}: {target.url}')
				return cdp_session
			except Exception as e:
				self.logger.debug(f'Failed to get session for target {node.target_id}: {e}')

		if self.agent_focus_target_id:
			target = self.session_manager.get_target(self.agent_focus_target_id)
			try:
				cdp_session = await self.get_or_create_cdp_session(self.agent_focus_target_id, focus=False)
				if target:
					self.logger.warning(
						f'Node {node.backend_node_id} has no session/frame/target info. Using agent_focus session: {target.url}'
					)
				return cdp_session
			except ValueError:
				pass

		self.logger.error(f'No session info for node {node.backend_node_id} and no agent_focus available. Using main session.')
		return await self.get_or_create_cdp_session()
