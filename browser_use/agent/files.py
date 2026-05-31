from typing import Any

from browser_use.filesystem.file_system import FileSystem


class AgentFileSystemMixin:
	has_downloads_path: bool
	browser_session: Any
	_last_known_downloads: list[str]
	available_file_paths: list[str] | None
	logger: Any
	state: Any
	file_system: FileSystem
	file_system_path: str
	agent_directory: Any
	screenshot_service: Any

	async def _check_and_update_downloads(self, context: str = '') -> None:
		"""Check for new downloads and update available file paths."""
		if not self.has_downloads_path:
			return

		assert self.browser_session is not None, 'BrowserSession is not set up'

		try:
			current_downloads = self.browser_session.downloaded_files
			if current_downloads != self._last_known_downloads:
				self._update_available_file_paths(current_downloads)
				self._last_known_downloads = current_downloads
				if context:
					self.logger.debug(f'📁 {context}: Updated available files')
		except Exception as e:
			error_context = f' {context}' if context else ''
			self.logger.debug(f'📁 Failed to check for downloads{error_context}: {type(e).__name__}: {e}')

	def _update_available_file_paths(self, downloads: list[str]) -> None:
		"""Update available_file_paths with downloaded files."""
		if not self.has_downloads_path:
			return

		current_files = set(self.available_file_paths or [])
		new_files = set(downloads) - current_files

		if new_files:
			self.available_file_paths = list(current_files | new_files)

			self.logger.info(
				f'📁 Added {len(new_files)} downloaded files to available_file_paths (total: {len(self.available_file_paths)} files)'
			)
			for file_path in new_files:
				self.logger.info(f'📄 New file available: {file_path}')
		else:
			self.logger.debug(f'📁 No new downloads detected (tracking {len(current_files)} files)')

	def _set_file_system(self, file_system_path: str | None = None) -> None:
		if self.state.file_system_state and file_system_path:
			raise ValueError(
				'Cannot provide both file_system_state (from agent state) and file_system_path. '
				'Either restore from existing state or create new file system at specified path, not both.'
			)

		if self.state.file_system_state:
			try:
				self.file_system = FileSystem.from_state(self.state.file_system_state)
				self.file_system_path = str(self.file_system.base_dir)
				self.logger.debug(f'💾 File system restored from state to: {self.file_system_path}')
				return
			except Exception as e:
				self.logger.error(f'💾 Failed to restore file system from state: {e}')
				raise e

		try:
			if file_system_path:
				self.file_system = FileSystem(file_system_path)
				self.file_system_path = file_system_path
			else:
				self.file_system = FileSystem(self.agent_directory)
				self.file_system_path = str(self.agent_directory)
		except Exception as e:
			self.logger.error(f'💾 Failed to initialize file system: {e}.')
			raise e

		self.state.file_system_state = self.file_system.get_state()
		self.logger.debug(f'💾 File system path: {self.file_system_path}')

	def _set_screenshot_service(self) -> None:
		"""Initialize screenshot service using agent directory."""
		try:
			from browser_use.screenshots.service import ScreenshotService

			self.screenshot_service = ScreenshotService(self.agent_directory)
			self.logger.debug(f'📸 Screenshot service initialized in: {self.agent_directory}/screenshots')
		except Exception as e:
			self.logger.error(f'📸 Failed to initialize screenshot service: {e}.')
			raise e

	def save_file_system_state(self) -> None:
		"""Save current file system state to agent state."""
		if self.file_system:
			self.state.file_system_state = self.file_system.get_state()
		else:
			self.logger.error('💾 File system is not set up. Cannot save state.')
			raise ValueError('File system is not set up. Cannot save state.')
