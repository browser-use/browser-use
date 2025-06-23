import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

INVALID_FILENAME_ERROR_MESSAGE = 'Error: Invalid filename format. Must be alphanumeric with .txt or .md extension.'


class FileSystem:
	def __init__(self, dir_path: str):
		# Create a base directory
		self.base_dir = Path(dir_path)
		self.base_dir.mkdir(parents=True, exist_ok=True)

		# Create and use a dedicated subfolder for all operations
		self.dir = self.base_dir / 'data_storage'
		if self.dir.exists():
			raise ValueError(
				'File system directory already exists - stopping for safety purposes. Please delete it first if you want to use this directory.'
			)
		self.dir.mkdir(exist_ok=True)

		# Initialize default files
		self.results_file = self.dir / 'results.md'
		self.todo_file = self.dir / 'todo.md'
		self.results_file.touch(exist_ok=True)
		self.todo_file.touch(exist_ok=True)
		self.extracted_content_count = 0

	def get_dir(self) -> Path:
		return self.dir

	async def save_extracted_content(self, content: str) -> str:
		extracted_content_file_name = f'extracted_content_{self.extracted_content_count}.md'
		result = await self.write_file(extracted_content_file_name, content)
		self.extracted_content_count += 1
		return result

	def _is_valid_filename(self, file_name: str) -> bool:
		"""Check if filename matches the required pattern: name.extension"""
		pattern = r'^[a-zA-Z0-9_\-]+\.(txt|md)$'
		return bool(re.match(pattern, file_name))

	def display_file(self, file_name: str) -> str | None:
		if not self._is_valid_filename(file_name):
			return None

		path = self.dir / file_name
		if not path.exists():
			return None
		try:
			return path.read_text()
		except Exception:
			return None

	async def read_file(self, file_name: str) -> str:
		if not self._is_valid_filename(file_name):
			return INVALID_FILENAME_ERROR_MESSAGE

		path = self.dir / file_name
		if not path.exists():
			return f"File '{file_name}' not found."

		try:
			# Create a new executor for this operation
			with ThreadPoolExecutor() as executor:
				# Run file read in a thread to avoid blocking
				content = await asyncio.get_event_loop().run_in_executor(executor, lambda: path.read_text())
			return f'Read from file {file_name}.\n<content>\n{content}\n</content>'
		except Exception:
			return f"Error: Could not read file '{file_name}'."

	async def write_file(self, file_name: str, content: str) -> str:
		if not self._is_valid_filename(file_name):
			return INVALID_FILENAME_ERROR_MESSAGE

		try:
			path = self.dir / file_name
			# Create a new executor for this operation
			with ThreadPoolExecutor() as executor:
				# Run file write in a thread to avoid blocking
				await asyncio.get_event_loop().run_in_executor(executor, lambda: path.write_text(content))
			return f'Data written to {file_name} successfully.'
		except Exception:
			return f"Error: Could not write to file '{file_name}'."

	async def append_file(self, file_name: str, content: str) -> str:
		if not self._is_valid_filename(file_name):
			return INVALID_FILENAME_ERROR_MESSAGE

		path = self.dir / file_name
		if not path.exists():
			return f"File '{file_name}' not found."
		try:
			# Create a new executor for this operation
			with ThreadPoolExecutor() as executor:
				# Run file append in a thread to avoid blocking
				def append_to_file():
					with path.open('a') as f:
						f.write(content)

				await asyncio.get_event_loop().run_in_executor(executor, append_to_file)
			return f'Data appended to {file_name} successfully.'
		except Exception as e:
			return f"Error: Could not append to file '{file_name}'. {str(e)}"

	def describe(self) -> str:
		"""List all files with their content information.

		Example output:
		<file>
		results.md - 42 lines
		<content>
		{preview_start}
		... {n_lines} more lines ...
		{preview_end}
		</content>
		</file>
		"""
		DISPLAY_CHARS = 400  # Total characters to display (split between start and end)
		description = ''

		for f in self.dir.iterdir():
			# Only process files and skip todo.md
			if (not f.is_file()) or f.name == 'todo.md':
				continue

			try:
				content = f.read_text()

				# Handle empty files
				if not content:
					description += f'<file>\n{f.name} - [empty file]\n</file>\n\n'
					continue

				lines = content.splitlines()
				line_count = len(lines)

				# For small files, display the entire content
				whole_file_description = f'<file>\n{f.name} - {line_count} lines\n<content>\n{content}\n</content>\n</file>\n'
				if len(content) < int(1.5 * DISPLAY_CHARS):
					description += whole_file_description
					continue

				# For larger files, display start and end previews
				half_display_chars = DISPLAY_CHARS // 2

				# Get start preview
				start_preview = ''
				start_line_count = 0
				chars_count = 0
				for line in lines:
					if chars_count + len(line) + 1 > half_display_chars:
						break
					start_preview += line + '\n'
					chars_count += len(line) + 1
					start_line_count += 1

				# Get end preview
				end_preview = ''
				end_line_count = 0
				chars_count = 0
				for line in reversed(lines):
					if chars_count + len(line) + 1 > half_display_chars:
						break
					end_preview = line + '\n' + end_preview
					chars_count += len(line) + 1
					end_line_count += 1

				# Calculate lines in between
				middle_line_count = line_count - start_line_count - end_line_count
				if middle_line_count <= 0:
					# display the entire file
					description += whole_file_description
					continue

				start_preview = start_preview.strip('\n').rstrip()
				end_preview = end_preview.strip('\n').rstrip()

				# Format output
				description += f'<file>\n{f.name} - {line_count} lines\n<content>\n{start_preview}\n'
				description += f'... {middle_line_count} more lines ...\n'
				description += f'{end_preview}\n'
				description += '</content>\n</file>\n'

			except Exception:
				description += f'<file>\n{f.name} - [error reading file]\n</file>\n\n'

		return description.strip('\n')

	def get_todo_contents(self) -> str:
		return self.todo_file.read_text()
