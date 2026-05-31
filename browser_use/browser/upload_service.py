from __future__ import annotations

import os

from browser_use.browser.service_base import BrowserService
from browser_use.browser.views import BrowserError
from browser_use.dom.service import EnhancedDOMTreeNode


class UploadService(BrowserService):
	"""File upload operations."""

	async def upload_file(self, node: EnhancedDOMTreeNode, file_path: str) -> None:
		index_for_logging = node.backend_node_id or 'unknown'
		if not self.browser_session.is_file_input(node):
			msg = f'Upload failed - element {index_for_logging} is not a file input.'
			raise BrowserError(message=msg, long_term_memory=msg)

		if os.path.exists(file_path):
			file_size = os.path.getsize(file_path)
			if file_size == 0:
				msg = f'Upload failed - file {file_path} is empty (0 bytes).'
				raise BrowserError(message=msg, long_term_memory=msg)
			self.browser_session.logger.debug(f'📎 File {file_path} validated ({file_size} bytes)')

		cdp_session = await self.browser_session.cdp_client_for_node(node)
		await cdp_session.cdp_client.send.DOM.setFileInputFiles(
			params={
				'files': [file_path],
				'backendNodeId': node.backend_node_id,
			},
			session_id=cdp_session.session_id,
		)

		self.browser_session.logger.info(f'📎 Uploaded file {file_path} to element {index_for_logging}')
