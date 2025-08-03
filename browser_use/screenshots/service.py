"""
Screenshot storage service for browser-use agents.
"""

import base64
from pathlib import Path

import anyio


class ScreenshotService:
	"""Simple screenshot storage service that saves screenshots to disk"""

	def __init__(self, agent_directory: str | Path):
		"""Initialize with agent directory path"""
		self.agent_directory = Path(agent_directory) if isinstance(agent_directory, str) else agent_directory

		# Create screenshots subdirectory
		self.screenshots_dir = self.agent_directory / 'screenshots'
		self.screenshots_dir.mkdir(parents=True, exist_ok=True)

	async def store_screenshot(self, screenshot_b64: str, step_number: int) -> str:
		"""Store screenshot to disk and return the full path as string"""
		screenshot_filename = f'step_{step_number}.png'
		screenshot_path = self.screenshots_dir / screenshot_filename

		# Decode base64 and save to disk
		screenshot_data = base64.b64decode(screenshot_b64)

		async with await anyio.open_file(screenshot_path, 'wb') as f:
			await f.write(screenshot_data)

		return str(screenshot_path)

	async def get_screenshot(self, screenshot_path: str) -> str | None:
		"""Load screenshot from disk path and return as base64"""
		if not screenshot_path:
			return None

		path = Path(screenshot_path)
		if not path.exists():
			return None

		# Load from disk and encode to base64
		async with await anyio.open_file(path, 'rb') as f:
			screenshot_data = await f.read()

		return base64.b64encode(screenshot_data).decode('utf-8')
