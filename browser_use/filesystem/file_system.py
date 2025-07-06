import asyncio
import re
import shutil
import tempfile
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

INVALID_FILENAME_ERROR_MESSAGE = 'Error: Invalid filename format. Must be alphanumeric with supported extension.'
DEFAULT_FILE_SYSTEM_PATH = 'browseruse_agent_data'


class FileSystemError(Exception):
	"""Custom exception for file system operations that should be shown to LLM"""

	pass


class BaseFile(BaseModel, ABC):
	"""Base class for all file types"""

	name: str
	content: str = ''

	# --- Subclass must define this ---
	@property
	@abstractmethod
	def extension(self) -> str:
		"""File extension (e.g. 'txt', 'md')"""
		pass

	def write_file_content(self, content: str) -> None:
		"""Update internal content (formatted)"""
		self.update_content(content)

	def append_file_content(self, content: str) -> None:
		"""Append content to internal content"""
		self.update_content(self.content + content)

	# --- These are shared and implemented here ---

	def update_content(self, content: str) -> None:
		self.content = content

	def sync_to_disk_sync(self, path: Path) -> None:
		file_path = path / self.full_name
		file_path.write_text(self.content)

	async def sync_to_disk(self, path: Path) -> None:
		file_path = path / self.full_name
		with ThreadPoolExecutor() as executor:
			await asyncio.get_event_loop().run_in_executor(executor, lambda: file_path.write_text(self.content))

	async def write(self, content: str, path: Path) -> None:
		self.write_file_content(content)
		await self.sync_to_disk(path)

	async def append(self, content: str, path: Path) -> None:
		self.append_file_content(content)
		await self.sync_to_disk(path)

	def read(self) -> str:
		return self.content

	@property
	def full_name(self) -> str:
		return f'{self.name}.{self.extension}'

	@property
	def get_size(self) -> int:
		return len(self.content)

	@property
	def get_line_count(self) -> int:
		return len(self.content.splitlines())


class MarkdownFile(BaseFile):
	"""Markdown file implementation"""

	@property
	def extension(self) -> str:
		return 'md'


class TxtFile(BaseFile):
	"""Plain text file implementation"""

	@property
	def extension(self) -> str:
		return 'txt'


class JsonFile(BaseFile):
	"""JSON file implementation"""

	@property
	def extension(self) -> str:
		return 'json'


class CsvFile(BaseFile):
	"""CSV file implementation"""

	@property
	def extension(self) -> str:
		return 'csv'


class FileSystemState(BaseModel):
	"""Serializable state of the file system"""

	files: dict[str, dict[str, Any]] = Field(default_factory=dict)  # full filename -> file data
	base_dir: str
	extracted_content_count: int = 0


class FileSystem:
	"""Enhanced file system with in-memory storage and multiple file type support"""

	def __init__(self, base_dir: str | Path, create_default_files: bool = True):
		# Handle the Path conversion before calling super().__init__
		self.base_dir = Path(base_dir) if isinstance(base_dir, str) else base_dir
		self.base_dir.mkdir(parents=True, exist_ok=True)

		# Create and use a dedicated subfolder for all operations
		self.data_dir = self.base_dir / DEFAULT_FILE_SYSTEM_PATH
		if self.data_dir.exists():
			# clean the data directory
			shutil.rmtree(self.data_dir)
		self.data_dir.mkdir(exist_ok=True)

		self._file_types: dict[str, type[BaseFile]] = {
			'md': MarkdownFile,
			'txt': TxtFile,
			'json': JsonFile,
			'csv': CsvFile,
		}

		self.files = {}
		if create_default_files:
			self.default_files = ['todo.md']
			self._create_default_files()

		self.extracted_content_count = 0

	def get_allowed_extensions(self) -> list[str]:
		"""Get allowed extensions"""
		return list(self._file_types.keys())

	def _get_file_type_class(self, extension: str) -> type[BaseFile] | None:
		"""Get the appropriate file class for an extension."""
		return self._file_types.get(extension.lower(), None)

	def _create_default_files(self) -> None:
		"""Create default results and todo files"""
		for full_filename in self.default_files:
			name_without_ext, extension = self._parse_filename(full_filename)
			file_class = self._get_file_type_class(extension)
			if not file_class:
				raise ValueError(f"Error: Invalid file extension '{extension}' for file '{full_filename}'.")

			file_obj = file_class(name=name_without_ext)
			self.files[full_filename] = file_obj  # Use full filename as key
			file_obj.sync_to_disk_sync(self.data_dir)

	def _is_valid_filename(self, file_name: str) -> bool:
		"""Check if filename matches the required pattern: name.extension"""
		# Build extensions pattern from _file_types
		extensions = '|'.join(self._file_types.keys())
		pattern = rf'^[a-zA-Z0-9_\-]+\.({extensions})$'
		return bool(re.match(pattern, file_name))

	def _parse_filename(self, filename: str) -> tuple[str, str]:
		"""Parse filename into name and extension. Always check _is_valid_filename first."""
		name, extension = filename.rsplit('.', 1)
		return name, extension.lower()

	def get_dir(self) -> Path:
		"""Get the file system directory"""
		return self.data_dir

	def get_file(self, full_filename: str) -> BaseFile | None:
		"""Get a file object by full filename"""
		if not self._is_valid_filename(full_filename):
			return None

		# Use full filename as key
		return self.files.get(full_filename)

	def list_files(self) -> list[str]:
		"""List all files in the system"""
		return [file_obj.full_name for file_obj in self.files.values()]

	def display_file(self, full_filename: str) -> str | None:
		"""Display file content using file-specific display method"""
		if not self._is_valid_filename(full_filename):
			return None

		file_obj = self.get_file(full_filename)
		if not file_obj:
			return None

		return file_obj.read()

	async def read_file(self, full_filename: str, external_file: bool = False) -> str:
		"""Read file content using file-specific read method and return appropriate message to LLM"""
		if external_file:
			try:
				try:
					_, extension = self._parse_filename(full_filename)
				except Exception:
					return f'Error: Invalid filename format {full_filename}. Must be alphanumeric with a supported extension.'
				if extension in ['md', 'txt', 'json', 'csv']:
					import anyio

					async with await anyio.open_file(full_filename, 'r') as f:
						content = await f.read()
						return f'Read from file {full_filename}.\n<content>\n{content}\n</content>'
				elif extension == 'pdf':
					import pypdf

					reader = pypdf.PdfReader(full_filename)
					num_pages = len(reader.pages)
					MAX_PDF_PAGES = 5
					extra_pages = num_pages - MAX_PDF_PAGES
					extracted_text = ''
					for page in reader.pages[:MAX_PDF_PAGES]:
						extracted_text += page.extract_text()
					extra_pages_text = f'{extra_pages} more pages...' if extra_pages > 0 else ''
					return f'Read from file {full_filename}.\n<content>\n{extracted_text}\n{extra_pages_text}</content>'
				else:
					return f'Error: Cannot read file {full_filename} as {extension} extension is not supported.'
			except FileNotFoundError:
				return f"Error: File '{full_filename}' not found."
			except PermissionError:
				return f"Error: Permission denied to read file '{full_filename}'."
			except Exception as e:
				return f"Error: Could not read file '{full_filename}'."

		if not self._is_valid_filename(full_filename):
			return INVALID_FILENAME_ERROR_MESSAGE

		file_obj = self.get_file(full_filename)
		if not file_obj:
			return f"File '{full_filename}' not found."

		try:
			content = file_obj.read()
			return f'Read from file {full_filename}.\n<content>\n{content}\n</content>'
		except FileSystemError as e:
			return str(e)
		except Exception:
			return f"Error: Could not read file '{full_filename}'."

	async def write_file(self, full_filename: str, content: str) -> str:
		"""Write content to file using file-specific write method"""
		if not self._is_valid_filename(full_filename):
			return INVALID_FILENAME_ERROR_MESSAGE

		try:
			name_without_ext, extension = self._parse_filename(full_filename)
			file_class = self._get_file_type_class(extension)
			if not file_class:
				raise ValueError(f"Error: Invalid file extension '{extension}' for file '{full_filename}'.")

			# Create or get existing file using full filename as key
			if full_filename in self.files:
				file_obj = self.files[full_filename]
			else:
				file_obj = file_class(name=name_without_ext)
				self.files[full_filename] = file_obj  # Use full filename as key

			# Use file-specific write method
			await file_obj.write(content, self.data_dir)
			return f'Data written to file {full_filename} successfully.'
		except FileSystemError as e:
			return str(e)
		except Exception as e:
			return f"Error: Could not write to file '{full_filename}'. {str(e)}"

	async def append_file(self, full_filename: str, content: str) -> str:
		"""Append content to file using file-specific append method"""
		if not self._is_valid_filename(full_filename):
			return INVALID_FILENAME_ERROR_MESSAGE

		file_obj = self.get_file(full_filename)
		if not file_obj:
			return f"File '{full_filename}' not found."

		try:
			await file_obj.append(content, self.data_dir)
			return f'Data appended to file {full_filename} successfully.'
		except FileSystemError as e:
			return str(e)
		except Exception as e:
			return f"Error: Could not append to file '{full_filename}'. {str(e)}"

	async def save_extracted_content(self, content: str) -> str:
		"""Save extracted content to a numbered file"""
		initial_filename = f'extracted_content_{self.extracted_content_count}'
		extracted_filename = f'{initial_filename}.md'
		file_obj = MarkdownFile(name=initial_filename)
		await file_obj.write(content, self.data_dir)
		self.files[extracted_filename] = file_obj
		self.extracted_content_count += 1
		return f'Extracted content saved to file {extracted_filename} successfully.'

	def describe(self) -> str:
		"""List all files with their content information using file-specific display methods"""
		DISPLAY_CHARS = 400
		description = ''

		for file_obj in self.files.values():
			# Skip todo.md from description
			if file_obj.full_name == 'todo.md':
				continue

			content = file_obj.read()

			# Handle empty files
			if not content:
				description += f'<file>\n{file_obj.full_name} - [empty file]\n</file>\n'
				continue

			lines = content.splitlines()
			line_count = len(lines)

			# For small files, display the entire content
			whole_file_description = (
				f'<file>\n{file_obj.full_name} - {line_count} lines\n<content>\n{content}\n</content>\n</file>\n'
			)
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
				description += whole_file_description
				continue

			start_preview = start_preview.strip('\n').rstrip()
			end_preview = end_preview.strip('\n').rstrip()

			# Format output
			if not (start_preview or end_preview):
				description += f'<file>\n{file_obj.full_name} - {line_count} lines\n<content>\n{middle_line_count} lines...\n</content>\n</file>\n'
			else:
				description += f'<file>\n{file_obj.full_name} - {line_count} lines\n<content>\n{start_preview}\n'
				description += f'... {middle_line_count} more lines ...\n'
				description += f'{end_preview}\n'
				description += '</content>\n</file>\n'

		return description.strip('\n')

	def get_todo_contents(self) -> str:
		"""Get todo file contents"""
		todo_file = self.get_file('todo.md')
		return todo_file.read() if todo_file else ''

	def get_state(self) -> FileSystemState:
		"""Get serializable state of the file system"""
		files_data = {}
		for full_filename, file_obj in self.files.items():
			files_data[full_filename] = {'type': file_obj.__class__.__name__, 'data': file_obj.model_dump()}

		return FileSystemState(
			files=files_data, base_dir=str(self.base_dir), extracted_content_count=self.extracted_content_count
		)

	def nuke(self) -> None:
		"""Delete the file system directory"""
		shutil.rmtree(self.data_dir)

	@classmethod
	def from_state(cls, state: FileSystemState) -> 'FileSystem':
		"""Restore file system from serializable state at the exact same location"""
		# Create file system without default files
		fs = cls(base_dir=Path(state.base_dir), create_default_files=False)
		fs.extracted_content_count = state.extracted_content_count

		# Restore all files
		for full_filename, file_data in state.files.items():
			file_type = file_data['type']
			file_info = file_data['data']

			# Create the appropriate file object based on type
			if file_type == 'MarkdownFile':
				file_obj = MarkdownFile(**file_info)
			elif file_type == 'TxtFile':
				file_obj = TxtFile(**file_info)
			elif file_type == 'JsonFile':
				file_obj = JsonFile(**file_info)
			elif file_type == 'CsvFile':
				file_obj = CsvFile(**file_info)
			else:
				# Skip unknown file types
				continue

			# Add to files dict and sync to disk
			fs.files[full_filename] = file_obj
			file_obj.sync_to_disk_sync(fs.data_dir)

		return fs


if __name__ == '__main__':
	# test to understand what model_dump() does
	md_file = MarkdownFile(name='test.md')
	md_file.update_content('Hello, world!')
	print(md_file.model_dump())

	# test to understand how state looks like
	tempdir = tempfile.gettempdir()
	fs = FileSystem(base_dir=Path(tempdir) / 'browseruse_test_data')
	print(fs.get_state())
	fs.nuke()

	# test to understand creating a filesystem, getting its state, and restoring it
	fs = FileSystem(base_dir=Path(tempdir) / 'browseruse_test_data')
	state = fs.get_state()
	print(state)
	fs2 = FileSystem.from_state(state)
	print(fs2.get_state())
	fs2.nuke()
