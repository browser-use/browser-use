"""Tests for image file support in the FileSystem."""

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from browser_use.filesystem.file_system import FileSystem


class TestImageFiles:
	"""Test image file operations - only external reading supported."""

	def create_test_image(self, width: int = 100, height: int = 100, format: str = 'PNG') -> bytes:
		"""Create a test image and return bytes."""
		img = Image.new('RGB', (width, height), color='red')
		buffer = io.BytesIO()
		img.save(buffer, format=format)
		buffer.seek(0)
		return buffer.read()

	@pytest.mark.asyncio
	async def test_read_external_png_image(self, tmp_path: Path):
		"""Test reading external PNG image file."""
		# Create an external image file
		external_file = tmp_path / 'test.png'
		img_bytes = self.create_test_image(width=300, height=200, format='PNG')
		external_file.write_bytes(img_bytes)

		fs = FileSystem(tmp_path / 'workspace')
		structured_result = await fs.read_file_structured(str(external_file), external_file=True)

		assert 'message' in structured_result
		assert 'Read image file' in structured_result['message']
		assert 'images' in structured_result
		assert structured_result['images'] is not None
		assert len(structured_result['images']) == 1

		img_data = structured_result['images'][0]
		assert img_data['name'] == 'test.png'
		assert 'data' in img_data
		# Verify base64 is valid
		decoded = base64.b64decode(img_data['data'])
		assert decoded == img_bytes

	@pytest.mark.asyncio
	async def test_read_external_jpg_image(self, tmp_path: Path):
		"""Test reading external JPG image file."""
		# Create an external image file
		external_file = tmp_path / 'photo.jpg'
		img_bytes = self.create_test_image(width=150, height=100, format='JPEG')
		external_file.write_bytes(img_bytes)

		fs = FileSystem(tmp_path / 'workspace')
		structured_result = await fs.read_file_structured(str(external_file), external_file=True)

		assert 'message' in structured_result
		assert 'images' in structured_result
		assert structured_result['images'] is not None

		img_data = structured_result['images'][0]
		assert img_data['name'] == 'photo.jpg'
		decoded = base64.b64decode(img_data['data'])
		assert len(decoded) > 0

	@pytest.mark.asyncio
	async def test_read_jpeg_extension(self, tmp_path: Path):
		"""Test reading .jpeg extension (not just .jpg)."""
		external_file = tmp_path / 'test.jpeg'
		img_bytes = self.create_test_image(format='JPEG')
		external_file.write_bytes(img_bytes)

		fs = FileSystem(tmp_path / 'workspace')
		structured_result = await fs.read_file_structured(str(external_file), external_file=True)

		assert structured_result['images'] is not None
		assert structured_result['images'][0]['name'] == 'test.jpeg'

	@pytest.mark.asyncio
	async def test_read_nonexistent_image(self, tmp_path: Path):
		"""Test reading a nonexistent image file."""
		fs = FileSystem(tmp_path / 'workspace')
		structured_result = await fs.read_file_structured('/path/to/nonexistent.png', external_file=True)

		assert 'message' in structured_result
		assert 'not found' in structured_result['message'].lower()
		assert structured_result['images'] is None

	@pytest.mark.asyncio
	async def test_corrupted_image_file(self, tmp_path: Path):
		"""Test reading a corrupted image file."""
		external_file = tmp_path / 'corrupted.png'
		# Write invalid PNG data
		external_file.write_bytes(b'Not a valid PNG file')

		fs = FileSystem(tmp_path / 'workspace')
		structured_result = await fs.read_file_structured(str(external_file), external_file=True)

		# Should still return base64 data (we don't validate image format)
		assert 'message' in structured_result
		assert 'Read image file' in structured_result['message']
		# Base64 encoding will succeed even for invalid image data
		assert structured_result['images'] is not None

	@pytest.mark.asyncio
	async def test_large_image_file(self, tmp_path: Path):
		"""Test reading a large image file."""
		# Create a large image (2000x2000)
		external_file = tmp_path / 'large.png'
		img = Image.new('RGB', (2000, 2000), color='blue')
		img.save(str(external_file), format='PNG')

		fs = FileSystem(tmp_path / 'workspace')
		structured_result = await fs.read_file_structured(str(external_file), external_file=True)

		assert 'images' in structured_result
		assert structured_result['images'] is not None
		# Verify base64 data is present and substantial
		assert len(structured_result['images'][0]['data']) > 10000

	@pytest.mark.asyncio
	async def test_multiple_images_in_sequence(self, tmp_path: Path):
		"""Test reading multiple images in sequence."""
		fs = FileSystem(tmp_path / 'workspace')

		# Create three different images
		for i, color in enumerate(['red', 'green', 'blue']):
			img_file = tmp_path / f'image_{i}.png'
			img = Image.new('RGB', (100, 100), color=color)
			img.save(str(img_file), format='PNG')

		# Read them all
		results = []
		for i in range(3):
			img_file = tmp_path / f'image_{i}.png'
			result = await fs.read_file_structured(str(img_file), external_file=True)
			results.append(result)

		# Verify all were read successfully
		for i, result in enumerate(results):
			assert result['images'] is not None
			assert result['images'][0]['name'] == f'image_{i}.png'

	@pytest.mark.asyncio
	async def test_different_image_formats(self, tmp_path: Path):
		"""Test reading different image format variations."""
		fs = FileSystem(tmp_path / 'workspace')

		# Test .jpg
		jpg_file = tmp_path / 'test.jpg'
		img = Image.new('RGB', (50, 50), color='yellow')
		img.save(str(jpg_file), format='JPEG')
		result_jpg = await fs.read_file_structured(str(jpg_file), external_file=True)
		assert result_jpg['images'] is not None

		# Test .jpeg
		jpeg_file = tmp_path / 'test.jpeg'
		img.save(str(jpeg_file), format='JPEG')
		result_jpeg = await fs.read_file_structured(str(jpeg_file), external_file=True)
		assert result_jpeg['images'] is not None

		# Test .png
		png_file = tmp_path / 'test.png'
		img.save(str(png_file), format='PNG')
		result_png = await fs.read_file_structured(str(png_file), external_file=True)
		assert result_png['images'] is not None

	@pytest.mark.asyncio
	async def test_image_with_transparency(self, tmp_path: Path):
		"""Test reading PNG with transparency (RGBA)."""
		external_file = tmp_path / 'transparent.png'
		# Create RGBA image with transparency
		img = Image.new('RGBA', (100, 100), color=(255, 0, 0, 128))
		img.save(str(external_file), format='PNG')

		fs = FileSystem(tmp_path / 'workspace')
		structured_result = await fs.read_file_structured(str(external_file), external_file=True)

		assert structured_result['images'] is not None
		assert len(structured_result['images'][0]['data']) > 0


class TestActionResultImages:
	"""Test ActionResult with images field."""

	def test_action_result_with_images(self):
		"""Test creating ActionResult with images."""
		from browser_use.agent.views import ActionResult

		images = [{'name': 'test.png', 'data': 'base64_encoded_data_here'}]

		result = ActionResult(
			extracted_content='Read image file test.png',
			long_term_memory='Read image file test.png',
			images=images,
			include_extracted_content_only_once=True,
		)

		assert result.images is not None
		assert len(result.images) == 1
		assert result.images[0]['name'] == 'test.png'
		assert result.images[0]['data'] == 'base64_encoded_data_here'

	def test_action_result_without_images(self):
		"""Test ActionResult without images (default behavior)."""
		from browser_use.agent.views import ActionResult

		result = ActionResult(extracted_content='Some text', long_term_memory='Memory')

		assert result.images is None

	def test_action_result_with_multiple_images(self):
		"""Test ActionResult with multiple images."""
		from browser_use.agent.views import ActionResult

		images = [
			{'name': 'image1.png', 'data': 'base64_data_1'},
			{'name': 'image2.jpg', 'data': 'base64_data_2'},
		]

		result = ActionResult(
			extracted_content='Read multiple images',
			long_term_memory='Read image files',
			images=images,
			include_extracted_content_only_once=True,
		)

		assert result.images is not None
		assert len(result.images) == 2
		assert result.images[0]['name'] == 'image1.png'
		assert result.images[1]['name'] == 'image2.jpg'

	def test_action_result_with_empty_images_list(self):
		"""Test ActionResult with empty images list."""
		from browser_use.agent.views import ActionResult

		result = ActionResult(
			extracted_content='No images',
			images=[],
		)

		# Empty list is still valid
		assert result.images == []


if __name__ == '__main__':
	pytest.main([__file__, '-v'])
