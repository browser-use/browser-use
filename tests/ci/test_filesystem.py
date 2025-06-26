"""
Comprehensive tests for the enhanced file system implementation.

Tests cover:
1. File class functionality (MarkdownFile, TxtFile)
2. FileSystem initialization and setup
3. Filename validation and parsing
4. File operations (read, write, append)
5. File access methods (get_file, list_files, display_file)
6. Special methods (describe, save_extracted_content, get_todo_contents)
7. Serialization and deserialization
8. Display functionality with various file sizes
9. Error handling and edge cases
10. Key consistency for same-name different-extension files
"""

import tempfile
from pathlib import Path

import pytest

from browser_use.filesystem.file_system import (
	FileSystem,
	FileSystemState,
	MarkdownFile,
	TxtFile,
)


class TestFileClasses:
	"""Test individual file class functionality"""

	def test_markdown_file_properties(self):
		"""Test MarkdownFile basic properties and methods"""
		md_file = MarkdownFile(name='test', content='# Header\n\nContent')

		assert md_file.extension == 'md'
		assert md_file.full_name == 'test.md'
		assert md_file.validate_content('any string')
		assert md_file.read_file_content() == '# Header\n\nContent'
		assert md_file.get_line_count() == 3
		assert md_file.get_size() == 17

	def test_markdown_file_write_and_append(self):
		"""Test MarkdownFile write and append methods"""
		md_file = MarkdownFile(name='test', content='# Header\n\nContent')

		write_result = md_file.write_file_content('New content')
		assert 'successfully' in write_result.lower()
		assert md_file.content == 'New content'

		append_result = md_file.append_file_content('\nAppended')
		assert 'successfully' in append_result.lower()
		assert 'New content\nAppended' in md_file.content

	def test_txt_file_properties(self):
		"""Test TxtFile basic properties and methods"""
		txt_file = TxtFile(name='notes', content='Plain text content')

		assert txt_file.extension == 'txt'
		assert txt_file.full_name == 'notes.txt'
		assert txt_file.validate_content('any string')
		assert txt_file.read_file_content() == 'Plain text content'

	def test_txt_file_write_and_append(self):
		"""Test TxtFile write and append methods"""
		txt_file = TxtFile(name='notes', content='Initial content')

		write_result = txt_file.write_file_content('New text content')
		assert 'successfully' in write_result.lower()
		assert txt_file.content == 'New text content'

		append_result = txt_file.append_file_content('\nExtra line')
		assert 'successfully' in append_result.lower()
		assert 'New text content\nExtra line' in txt_file.content


class TestFileSystemInitialization:
	"""Test FileSystem initialization and basic setup"""

	def test_filesystem_directory_creation(self):
		"""Test that FileSystem creates proper directory structure"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			# Test directory exists
			assert fs.get_dir().exists()
			assert 'browseruse_agent_data' in str(fs.get_dir())

	def test_default_files_creation(self):
		"""Test that default files are created during initialization"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			# Test default files exist
			assert 'results.md' in fs.files
			assert 'todo.md' in fs.files
			assert fs.extracted_content_count == 0

			# Print initial description for verification
			initial_description = fs.describe()
			print(f'\n📋 INITIAL FILE SYSTEM DESCRIPTION:\n{initial_description}')

	def test_filesystem_state_initialization(self):
		"""Test that FileSystem properly initializes internal state"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			assert isinstance(fs.files, dict)
			assert len(fs.files) == 2  # results.md and todo.md
			assert fs.extracted_content_count == 0


class TestFilenameValidation:
	"""Test filename validation and parsing functionality"""

	def test_valid_filename_patterns(self):
		"""Test that valid filenames are correctly identified"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			valid_files = ['test.md', 'file_name.txt', 'test123.md', 'my-file.txt', 'my_file.md']
			for filename in valid_files:
				assert fs._is_valid_filename(filename), f'Should accept {filename}'

	def test_invalid_filename_patterns(self):
		"""Test that invalid filenames are correctly rejected"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			invalid_files = ['test.xyz', 'file.json', 'noextension', 'test.', '.md', 'test..md', 'test space.md']
			for filename in invalid_files:
				assert not fs._is_valid_filename(filename), f'Should reject {filename}'

	def test_filename_parsing(self):
		"""Test filename parsing into name and extension"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			name, ext = fs._parse_filename('test.md')
			assert name == 'test' and ext == 'md'

			name, ext = fs._parse_filename('complex_file-name.txt')
			assert name == 'complex_file-name' and ext == 'txt'

	def test_file_type_class_retrieval(self):
		"""Test that appropriate file classes are returned for extensions"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			md_class = fs._get_file_type_class('md')
			txt_class = fs._get_file_type_class('txt')
			unknown_class = fs._get_file_type_class('xyz')

			assert md_class == MarkdownFile
			assert txt_class == TxtFile
			assert unknown_class == TxtFile  # Default fallback


class TestFileOperations:
	"""Test all file operation methods"""

	async def test_write_file_operations(self):
		"""Test write_file method with various scenarios"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			# Test valid file write
			write_result = await fs.write_file('test1.md', '# Test Content')
			assert 'successfully' in write_result.lower()
			assert 'test1.md' in fs.files

			# Test file exists on disk
			disk_file = fs.get_dir() / 'test1.md'
			assert disk_file.exists()

			# Test invalid filename
			invalid_result = await fs.write_file('invalid.xyz', 'content')
			assert 'invalid filename format' in invalid_result.lower()

			# Print file system state
			operations_description = fs.describe()
			print(f'\n📋 FILE SYSTEM AFTER WRITE OPERATIONS:\n{operations_description}')

	async def test_read_file_operations(self):
		"""Test read_file method with various scenarios"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			# Write a test file first
			await fs.write_file('test1.md', '# Test Content')

			# Test reading existing file
			read_result = await fs.read_file('test1.md')
			assert 'Test Content' in read_result
			assert 'Read from file test1.md' in read_result

			# Test reading non-existent file
			not_found_result = await fs.read_file('nonexistent.md')
			assert 'not found' in not_found_result.lower()

			# Test invalid filename
			invalid_read = await fs.read_file('invalid.xyz')
			assert 'invalid filename format' in invalid_read.lower()

	async def test_append_file_operations(self):
		"""Test append_file method with various scenarios"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			# Write initial file
			await fs.write_file('test1.md', '# Test Content')

			# Test appending to existing file
			append_result = await fs.append_file('test1.md', '\n\nAppended content')
			assert 'successfully' in append_result.lower()

			# Verify append worked
			after_append = await fs.read_file('test1.md')
			assert 'Appended content' in after_append

			# Test append to non-existent file
			append_missing_result = await fs.append_file('missing.md', 'content')
			assert 'not found' in append_missing_result.lower()

			# Test invalid filename
			invalid_append = await fs.append_file('invalid.xyz', 'content')
			assert 'invalid filename format' in invalid_append.lower()


class TestFileAccessMethods:
	"""Test file access and listing methods"""

	async def test_get_file_method(self):
		"""Test get_file method functionality"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			# Add test files
			await fs.write_file('doc1.md', 'Document 1')
			await fs.write_file('doc2.txt', 'Document 2')
			await fs.write_file('same_name.md', 'Markdown version')
			await fs.write_file('same_name.txt', 'Text version')

			# Test getting existing file
			md_file = fs.get_file('doc1.md')
			assert md_file is not None
			assert md_file.content == 'Document 1'

			# Test getting files with same name but different extension
			same_md = fs.get_file('same_name.md')
			same_txt = fs.get_file('same_name.txt')
			assert same_md is not None and same_txt is not None
			assert same_md.content != same_txt.content
			assert same_md.content == 'Markdown version'
			assert same_txt.content == 'Text version'

	async def test_list_files_method(self):
		"""Test list_files method functionality"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			# Add test files
			await fs.write_file('doc1.md', 'Document 1')
			await fs.write_file('doc2.txt', 'Document 2')
			await fs.write_file('same_name.md', 'Markdown version')
			await fs.write_file('same_name.txt', 'Text version')

			file_list = fs.list_files()
			expected_files = {'results.md', 'todo.md', 'doc1.md', 'doc2.txt', 'same_name.md', 'same_name.txt'}
			assert set(file_list) == expected_files

			# Print file system state
			access_description = fs.describe()
			print(f'\n📋 FILE SYSTEM WITH MULTIPLE FILES:\n{access_description}')

	async def test_display_file_method(self):
		"""Test display_file method functionality"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			await fs.write_file('doc1.md', 'Document 1')

			# Test displaying existing file
			display_content = fs.display_file('doc1.md')
			assert display_content == 'Document 1'

			# Test displaying non-existent file
			display_none = fs.display_file('nonexistent.md')
			assert display_none is None


class TestSpecialMethods:
	"""Test special methods like describe, save_extracted_content, etc."""

	async def test_describe_method(self):
		"""Test describe method functionality"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			# Add content to test files
			await fs.write_file('results.md', '# Results\n\nSome results here')
			await fs.write_file('notes.txt', 'Short note')

			description = fs.describe()

			# Test that files are included/excluded properly
			assert 'results.md' in description
			assert 'notes.txt' in description
			assert 'todo.md' not in description  # Should be excluded

			# Test XML formatting
			assert '<file>' in description and '</file>' in description
			assert '<content>' in description and '</content>' in description

			print(f'\n📋 FILE SYSTEM DESCRIPTION TEST:\n{description}')

	async def test_get_todo_contents_method(self):
		"""Test get_todo_contents method functionality"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			await fs.write_file('todo.md', '# TODO\n\n- Task 1\n- Task 2')
			todo_contents = fs.get_todo_contents()

			assert 'Task 1' in todo_contents
			assert 'Task 2' in todo_contents

	async def test_save_extracted_content_method(self):
		"""Test save_extracted_content method functionality"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			initial_count = fs.extracted_content_count
			extract_result = await fs.save_extracted_content('Extracted data')

			assert 'successfully' in extract_result.lower()
			assert fs.extracted_content_count == initial_count + 1

			expected_filename = f'extracted_content_{initial_count}.md'
			assert expected_filename in fs.files

			# Print file system state
			special_description = fs.describe()
			print(f'\n📋 FILE SYSTEM AFTER SPECIAL METHODS:\n{special_description}')


class TestSerialization:
	"""Test serialization and deserialization functionality"""

	async def test_get_state_method(self):
		"""Test get_state method functionality"""
		with tempfile.TemporaryDirectory() as temp_dir:
			# Create filesystem with test data
			fs1 = FileSystem(temp_dir)
			await fs1.write_file('doc1.md', '# Document 1\n\nContent here')
			await fs1.write_file('doc2.txt', 'Plain text document')
			await fs1.write_file('same.md', 'Markdown version')
			await fs1.write_file('same.txt', 'Text version')
			fs1.extracted_content_count = 5

			state = fs1.get_state()

			assert isinstance(state, FileSystemState)
			expected_files = {'results.md', 'todo.md', 'doc1.md', 'doc2.txt', 'same.md', 'same.txt'}
			assert set(state.files.keys()) == expected_files
			assert state.extracted_content_count == 5

	async def test_from_state_method(self):
		"""Test from_state method functionality"""
		with tempfile.TemporaryDirectory() as temp_dir:
			# Create original filesystem
			fs1 = FileSystem(temp_dir)
			await fs1.write_file('doc1.md', '# Document 1\n\nContent here')
			await fs1.write_file('doc2.txt', 'Plain text document')
			await fs1.write_file('same.md', 'Markdown version')
			await fs1.write_file('same.txt', 'Text version')
			fs1.extracted_content_count = 5

			# Get state and restore
			state = fs1.get_state()
			fs2 = FileSystem.from_state(state)

			# Test restoration
			assert isinstance(fs2, FileSystem)
			expected_files = {'results.md', 'todo.md', 'doc1.md', 'doc2.txt', 'same.md', 'same.txt'}
			assert set(fs2.files.keys()) == expected_files
			assert fs2.extracted_content_count == 5

			# Test content preservation
			doc1_content = await fs2.read_file('doc1.md')
			assert 'Document 1' in doc1_content and 'Content here' in doc1_content

			# Test same name different extension preservation
			same_md_content = await fs2.read_file('same.md')
			same_txt_content = await fs2.read_file('same.txt')
			assert 'Markdown version' in same_md_content
			assert 'Text version' in same_txt_content

			# Print comparison
			original_description = fs1.describe()
			restored_description = fs2.describe()
			print(f'\n📋 ORIGINAL FILE SYSTEM:\n{original_description}')
			print(f'\n📋 RESTORED FILE SYSTEM:\n{restored_description}')

	async def test_from_state_disk_persistence(self):
		"""Test that from_state actually writes files to disk"""
		with tempfile.TemporaryDirectory() as temp_dir:
			# Create original filesystem
			fs1 = FileSystem(temp_dir)
			await fs1.write_file('test.md', '# Test Content\n\nThis is test content')
			await fs1.write_file('data.txt', 'Plain text data')

			# Get state and restore
			state = fs1.get_state()
			fs2 = FileSystem.from_state(state)

			# Verify files exist on disk in the restored filesystem
			test_md_path = fs2.get_dir() / 'test.md'
			data_txt_path = fs2.get_dir() / 'data.txt'

			assert test_md_path.exists(), 'test.md should exist on disk after restoration'
			assert data_txt_path.exists(), 'data.txt should exist on disk after restoration'

			# Verify content on disk matches
			disk_md_content = test_md_path.read_text()
			disk_txt_content = data_txt_path.read_text()

			assert '# Test Content' in disk_md_content
			assert 'Plain text data' in disk_txt_content

			print('\n📋 DISK PERSISTENCE TEST:')
			print(f'test.md exists: {test_md_path.exists()}')
			print(f'data.txt exists: {data_txt_path.exists()}')
			print(f'Disk content matches memory: {disk_md_content == fs2.files["test.md"].content}')

	async def test_from_state_functional_after_restoration(self):
		"""Test that restored filesystem is fully functional"""
		with tempfile.TemporaryDirectory() as temp_dir:
			# Create original filesystem
			fs1 = FileSystem(temp_dir)
			await fs1.write_file('original.md', 'Original content')

			# Get state and restore
			state = fs1.get_state()
			fs2 = FileSystem.from_state(state)

			# Test all operations work on restored filesystem
			# 1. Read existing file
			read_result = await fs2.read_file('original.md')
			assert 'Original content' in read_result

			# 2. Write new file
			write_result = await fs2.write_file('new.txt', 'New content after restoration')
			assert 'successfully' in write_result.lower()

			# 3. Append to existing file
			append_result = await fs2.append_file('original.md', '\nAppended after restoration')
			assert 'successfully' in append_result.lower()

			# 4. List files includes new file
			file_list = fs2.list_files()
			assert 'new.txt' in file_list

			# 5. Describe works
			description = fs2.describe()
			assert 'original.md' in description
			assert 'new.txt' in description

			print('\n📋 FUNCTIONALITY TEST AFTER RESTORATION:')
			print(f'Files: {file_list}')
			print(f'Description includes new content: {"Appended after restoration" in description}')

	async def test_from_state_with_empty_filesystem(self):
		"""Test restoration of an empty filesystem"""
		with tempfile.TemporaryDirectory() as temp_dir:
			# Create filesystem and clear default files
			fs1 = FileSystem(temp_dir)
			fs1.files.clear()  # Remove default files

			# Get state and restore
			state = fs1.get_state()
			fs2 = FileSystem.from_state(state)

			# Should have no files
			assert len(fs2.files) == 0
			assert fs2.list_files() == []

			# Should still be functional
			write_result = await fs2.write_file('first.md', 'First file in restored empty system')
			assert 'successfully' in write_result.lower()
			assert len(fs2.files) == 1

	async def test_from_state_extracted_content_counter(self):
		"""Test that extracted content counter is preserved"""
		with tempfile.TemporaryDirectory() as temp_dir:
			# Create filesystem and add extracted content
			fs1 = FileSystem(temp_dir)
			await fs1.save_extracted_content('Content 1')
			await fs1.save_extracted_content('Content 2')
			await fs1.save_extracted_content('Content 3')

			assert fs1.extracted_content_count == 3

			# Get state and restore
			state = fs1.get_state()
			fs2 = FileSystem.from_state(state)

			# Counter should be preserved
			assert fs2.extracted_content_count == 3

			# Next extracted content should use correct number
			await fs2.save_extracted_content('Content 4')
			assert fs2.extracted_content_count == 4
			assert 'extracted_content_3.md' in fs2.files

	async def test_from_state_with_complex_content(self):
		"""Test restoration with complex file content"""
		with tempfile.TemporaryDirectory() as temp_dir:
			# Create filesystem with complex content
			fs1 = FileSystem(temp_dir)

			complex_md = """# Complex Markdown File

## Section 1
This is a complex markdown file with:
- Lists
- **Bold text**
- `Code snippets`

### Subsection
More content here.

## Section 2
Final section with special characters: àáâãäå ñ ü ß"""

			complex_txt = """Line 1 with special chars: ~!@#$%^&*()_+
Line 2 with unicode: 你好世界
Line 3 with emojis: 🚀🎉📋
Line 4 with quotes: "double" and 'single'
Line 5 with backslashes: \\path\\to\\file"""

			await fs1.write_file('complex.md', complex_md)
			await fs1.write_file('complex.txt', complex_txt)

			# Get state and restore
			state = fs1.get_state()
			fs2 = FileSystem.from_state(state)

			# Verify complex content is preserved
			restored_md = await fs2.read_file('complex.md')
			restored_txt = await fs2.read_file('complex.txt')

			assert 'Complex Markdown File' in restored_md
			assert '你好世界' in restored_txt
			assert '🚀🎉📋' in restored_txt
			assert '\\path\\to\\file' in restored_txt

			print('\n📋 COMPLEX CONTENT TEST:')
			print(f'Special characters preserved: {"àáâãäå" in restored_md}')
			print(f'Unicode preserved: {"你好世界" in restored_txt}')
			print(f'Emojis preserved: {"🚀🎉📋" in restored_txt}')

	async def test_from_state_directory_structure(self):
		"""Test that from_state creates proper directory structure"""
		with tempfile.TemporaryDirectory() as temp_dir:
			# Create original filesystem
			fs1 = FileSystem(temp_dir)
			await fs1.write_file('test.md', 'content')

			# Get state
			state = fs1.get_state()

			# Verify state has correct path
			assert 'browseruse_agent_data' in state.base_dir

			# Restore to different location
			with tempfile.TemporaryDirectory() as new_temp_dir:
				# Modify state to point to new location
				new_state = FileSystemState(
					files=state.files,
					base_dir=str(Path(new_temp_dir) / 'browseruse_agent_data'),
					extracted_content_count=state.extracted_content_count,
				)

				fs2 = FileSystem.from_state(new_state)

				# Verify directory structure
				assert fs2.get_dir().exists()
				assert 'browseruse_agent_data' in str(fs2.get_dir())
				assert fs2.get_dir() != fs1.get_dir()  # Different locations

				# Verify file exists in new location
				test_file_path = fs2.get_dir() / 'test.md'
				assert test_file_path.exists()

				print('\n📋 DIRECTORY STRUCTURE TEST:')
				print(f'Original dir: {fs1.get_dir()}')
				print(f'Restored dir: {fs2.get_dir()}')
				print(f'File exists in new location: {test_file_path.exists()}')

	def test_from_state_error_handling(self):
		"""Test error handling in from_state method"""
		# Test with invalid file type in state
		invalid_state = FileSystemState(
			files={'invalid.md': {'type': 'NonExistentFileType', 'data': {'name': 'invalid', 'content': 'test'}}},
			base_dir='/tmp/test_invalid',
			extracted_content_count=0,
		)

		# Should fallback to TxtFile for unknown types
		fs = FileSystem.from_state(invalid_state)
		assert 'invalid.md' in fs.files
		assert isinstance(fs.files['invalid.md'], TxtFile)  # Should fallback to TxtFile

		print('\n📋 ERROR HANDLING TEST:')
		print(f'Unknown file type handled gracefully: {type(fs.files["invalid.md"]).__name__}')


class TestDisplayFunctionality:
	"""Test file system display functionality with various file sizes and content"""

	async def test_empty_file_display(self):
		"""Test display of empty files"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			await fs.write_file('empty.md', '')
			description = fs.describe()

			assert '[empty file]' in description
			print(f'\n📋 EMPTY FILE DISPLAY:\n{description}')

	async def test_small_file_display(self):
		"""Test display of small files (should show complete content)"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			small_content = '# Small File\n\nThis is a small file with just a few lines.\nLine 3\nLine 4'
			await fs.write_file('small.md', small_content)
			description = fs.describe()

			assert 'Small File' in description and 'Line 4' in description
			print(f'\n📋 SMALL FILE DISPLAY:\n{description}')

	async def test_medium_file_display(self):
		"""Test display of medium files (around threshold)"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			# Create content around threshold
			medium_lines = [f'This is line {i + 1} with some content to make it longer' for i in range(20)]
			medium_content = '\n'.join(medium_lines)
			await fs.write_file('medium.txt', medium_content)

			description = fs.describe()
			assert 'line 1' in description and 'line 20' in description
			print(f'\n📋 MEDIUM FILE DISPLAY:\n{description[:500]}...')

	async def test_large_file_display(self):
		"""Test display of large files (should show truncation)"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			# Create large content that will be truncated
			large_lines = []
			for i in range(100):
				large_lines.append(
					f'This is a very long line {i + 1} with lots of content to exceed the display character limit and force truncation behavior in the describe method'
				)
			large_content = '\n'.join(large_lines)
			await fs.write_file('large.md', large_content)

			description = fs.describe()
			assert 'line 1' in description and 'line 100' in description
			assert 'more lines' in description
			print(f'\n📋 LARGE FILE DISPLAY (truncated):\n{description[:800]}...')

	async def test_threshold_file_display(self):
		"""Test display of files at exact threshold"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			# Create content at threshold (590 chars)
			threshold_content = 'x' * 590
			await fs.write_file('threshold.txt', threshold_content)
			description = fs.describe()

			assert threshold_content[:50] in description
			print(f'\n📋 THRESHOLD FILE DISPLAY:\n{description}')

	async def test_line_count_accuracy(self):
		"""Test that line counts are displayed accurately"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			test_content = 'Line 1\nLine 2\nLine 3\nLine 4\nLine 5'
			await fs.write_file('linecount.md', test_content)
			description = fs.describe()

			assert '5 lines' in description

	async def test_xml_formatting(self):
		"""Test that XML formatting is correct"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			await fs.write_file('test.md', 'Test content')
			description = fs.describe()

			# Test balanced XML tags
			assert description.count('<file>') == description.count('</file>')
			assert '<content>' in description and '</content>' in description

	async def test_comprehensive_display_output(self):
		"""Test comprehensive display with all file types and sizes"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			# Create various types of files
			await fs.write_file('empty.md', '')
			await fs.write_file('small.txt', 'Short content')

			# Medium file
			medium_lines = [f'Line {i + 1} content' for i in range(15)]
			await fs.write_file('medium.md', '\n'.join(medium_lines))

			# Large file
			large_lines = [f'Very long line {i + 1} with extensive content for testing truncation behavior' for i in range(50)]
			await fs.write_file('large.txt', '\n'.join(large_lines))

			# Mixed file types
			await fs.write_file('mixed1.md', '# Markdown file\n\nWith some content')
			await fs.write_file('mixed2.txt', 'Plain text file\nWith some content')

			sample_description = fs.describe()

			print('\n📋 COMPREHENSIVE DISPLAY OUTPUT:')
			print('=' * 60)
			print(sample_description)
			print('=' * 60)
			print('\nDescription Statistics:')
			print(f'- Total length: {len(sample_description)} characters')
			print(f'- Total files in system: {len(fs.files)}')
			print(f'- Files shown in description: {sample_description.count("<file>")}')
			print(f'- Files with truncation: {sample_description.count("more lines")}')

			# Basic assertions
			assert len(sample_description) > 0
			assert sample_description.count('<file>') > 0


class TestErrorHandling:
	"""Test error handling and edge cases"""

	async def test_invalid_filename_error_handling(self):
		"""Test error handling for invalid filenames"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			# Test various invalid filename operations
			invalid_read = await fs.read_file('invalid.xyz')
			assert 'invalid filename format' in invalid_read.lower()

			invalid_write = await fs.write_file('invalid.xyz', 'content')
			assert 'invalid filename format' in invalid_write.lower()

			invalid_append = await fs.append_file('invalid.xyz', 'content')
			assert 'invalid filename format' in invalid_append.lower()

	async def test_nonexistent_file_error_handling(self):
		"""Test error handling for non-existent files"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			read_missing = await fs.read_file('missing.md')
			assert 'not found' in read_missing.lower()

			append_missing = await fs.append_file('missing.md', 'content')
			assert 'not found' in append_missing.lower()

	def test_get_file_with_invalid_filename(self):
		"""Test get_file with invalid filename returns None"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			result = fs.get_file('invalid.xyz')
			assert result is None

	def test_display_file_with_nonexistent_file(self):
		"""Test display_file with non-existent file returns None"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			result = fs.display_file('nonexistent.md')
			assert result is None


class TestKeyConsistency:
	"""Test that all dictionary keys consistently use full filenames"""

	async def test_full_filename_keys(self):
		"""Test that all dictionary keys use full filenames with extensions"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			# Add files with same names but different extensions
			await fs.write_file('test.md', 'Markdown content')
			await fs.write_file('test.txt', 'Text content')
			await fs.write_file('document.md', 'Another markdown')
			await fs.write_file('document.txt', 'Another text')

			all_keys = list(fs.files.keys())

			# Test all keys have extensions
			assert all('.' in key for key in all_keys)

			# Test no duplicate keys
			assert len(all_keys) == len(set(all_keys))

	async def test_same_name_different_extension_access(self):
		"""Test accessing files with same names but different extensions"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			await fs.write_file('test.md', 'Markdown content')
			await fs.write_file('test.txt', 'Text content')

			# Test both files are accessible
			test_md = await fs.read_file('test.md')
			test_txt = await fs.read_file('test.txt')

			assert 'Markdown content' in test_md
			assert 'Text content' in test_txt

	async def test_serialization_key_preservation(self):
		"""Test that serialization preserves full filename keys"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			await fs.write_file('test.md', 'Markdown content')
			await fs.write_file('test.txt', 'Text content')
			await fs.write_file('document.md', 'Another markdown')
			await fs.write_file('document.txt', 'Another text')

			all_keys = list(fs.files.keys())

			# Test serialization preserves keys
			state = fs.get_state()
			state_keys = list(state.files.keys())
			assert set(state_keys) == set(all_keys)

			# Test deserialization preserves keys
			fs2 = FileSystem.from_state(state)
			restored_keys = list(fs2.files.keys())
			assert set(restored_keys) == set(all_keys)

			# Print verification
			consistency_description = fs.describe()
			print(f'\n📋 SAME-NAME DIFFERENT-EXTENSION FILES:\n{consistency_description}')


class TestFileSystemDirectory:
	"""Test directory-related functionality"""

	def test_get_dir_method(self):
		"""Test get_dir method returns correct directory"""
		with tempfile.TemporaryDirectory() as temp_dir:
			fs = FileSystem(temp_dir)

			dir_path = fs.get_dir()
			assert isinstance(dir_path, Path)
			assert dir_path.exists()
			assert 'browseruse_agent_data' in str(dir_path)

	def test_directory_already_exists_error(self):
		"""Test that error is raised if directory already exists"""
		with tempfile.TemporaryDirectory() as temp_dir:
			# Create first filesystem
			fs1 = FileSystem(temp_dir)

			# Try to create second filesystem in same directory - should raise error
			with pytest.raises(ValueError, match='File system directory already exists'):
				fs2 = FileSystem(temp_dir)
