"""Integration tests for DOCX and image file support in LLM messages."""

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.prompts import AgentMessagePrompt
from browser_use.agent.views import ActionResult, AgentStepInfo
from browser_use.browser.views import BrowserStateSummary, TabInfo
from browser_use.dom.views import SerializedDOMState
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.messages import ContentPartImageParam, ContentPartTextParam, SystemMessage


class TestImageInLLMMessages:
	"""Test that images flow correctly through to LLM messages."""

	def create_test_image(self, width: int = 100, height: int = 100) -> bytes:
		"""Create a test image and return bytes."""
		img = Image.new('RGB', (width, height), color='red')
		buffer = io.BytesIO()
		img.save(buffer, format='PNG')
		buffer.seek(0)
		return buffer.read()

	@pytest.mark.asyncio
	async def test_image_stored_in_message_manager(self, tmp_path: Path):
		"""Test that images are stored in MessageManager state."""
		fs = FileSystem(tmp_path)
		system_message = SystemMessage(content='Test system message')
		mm = MessageManager(task='test', system_message=system_message, file_system=fs)

		# Create ActionResult with images
		images = [{'name': 'test.png', 'data': 'base64_test_data'}]
		action_results = [
			ActionResult(
				extracted_content='Read image file test.png',
				long_term_memory='Read image file test.png',
				images=images,
				include_extracted_content_only_once=True,
			)
		]

		# Update message manager with results
		step_info = AgentStepInfo(step_number=1, max_steps=10)
		mm._update_agent_history_description(model_output=None, result=action_results, step_info=step_info)

		# Verify images are stored
		assert mm.state.read_state_images is not None
		assert len(mm.state.read_state_images) == 1
		assert mm.state.read_state_images[0]['name'] == 'test.png'
		assert mm.state.read_state_images[0]['data'] == 'base64_test_data'

	@pytest.mark.asyncio
	async def test_images_cleared_after_step(self, tmp_path: Path):
		"""Test that images are cleared after each step."""
		fs = FileSystem(tmp_path)
		system_message = SystemMessage(content='Test system message')
		mm = MessageManager(task='test', system_message=system_message, file_system=fs)

		# First step with images
		images = [{'name': 'test.png', 'data': 'base64_data'}]
		action_results = [ActionResult(images=images, include_extracted_content_only_once=True)]
		step_info = AgentStepInfo(step_number=1, max_steps=10)
		mm._update_agent_history_description(model_output=None, result=action_results, step_info=step_info)

		assert len(mm.state.read_state_images) == 1

		# Second step without images - should clear
		action_results_2 = [ActionResult(extracted_content='No images')]
		step_info_2 = AgentStepInfo(step_number=2, max_steps=10)
		mm._update_agent_history_description(model_output=None, result=action_results_2, step_info=step_info_2)

		assert len(mm.state.read_state_images) == 0

	@pytest.mark.asyncio
	async def test_multiple_images_accumulated(self, tmp_path: Path):
		"""Test that multiple images in one step are accumulated."""
		fs = FileSystem(tmp_path)
		system_message = SystemMessage(content='Test system message')
		mm = MessageManager(task='test', system_message=system_message, file_system=fs)

		# Multiple action results with images
		action_results = [
			ActionResult(images=[{'name': 'img1.png', 'data': 'data1'}], include_extracted_content_only_once=True),
			ActionResult(images=[{'name': 'img2.jpg', 'data': 'data2'}], include_extracted_content_only_once=True),
		]
		step_info = AgentStepInfo(step_number=1, max_steps=10)
		mm._update_agent_history_description(model_output=None, result=action_results, step_info=step_info)

		assert len(mm.state.read_state_images) == 2
		assert mm.state.read_state_images[0]['name'] == 'img1.png'
		assert mm.state.read_state_images[1]['name'] == 'img2.jpg'

	def test_agent_message_prompt_includes_images(self, tmp_path: Path):
		"""Test that AgentMessagePrompt includes images in message content."""
		fs = FileSystem(tmp_path)

		# Create browser state
		browser_state = BrowserStateSummary(
			url='https://example.com',
			title='Test',
			tabs=[TabInfo(target_id='test-0', url='https://example.com', title='Test')],
			screenshot=None,
			dom_state=SerializedDOMState(_root=None, selector_map={}),
		)

		# Create images
		read_state_images = [{'name': 'test.png', 'data': 'base64_image_data_here'}]

		# Create message prompt
		prompt = AgentMessagePrompt(
			browser_state_summary=browser_state,
			file_system=fs,
			read_state_images=read_state_images,
		)

		# Get user message with vision enabled
		user_message = prompt.get_user_message(use_vision=True)

		# Verify message has content parts (not just string)
		assert isinstance(user_message.content, list)

		# Find image content parts
		image_parts = [part for part in user_message.content if isinstance(part, ContentPartImageParam)]
		text_parts = [part for part in user_message.content if isinstance(part, ContentPartTextParam)]

		# Should have at least one image
		assert len(image_parts) >= 1

		# Should have text label
		image_labels = [part.text for part in text_parts if 'test.png' in part.text]
		assert len(image_labels) >= 1

		# Verify image data URL format
		img_part = image_parts[0]
		assert 'data:image/' in img_part.image_url.url
		assert 'base64,base64_image_data_here' in img_part.image_url.url

	def test_agent_message_prompt_png_vs_jpg_media_type(self, tmp_path: Path):
		"""Test that AgentMessagePrompt correctly detects PNG vs JPG media types."""
		fs = FileSystem(tmp_path)

		browser_state = BrowserStateSummary(
			url='https://example.com',
			title='Test',
			tabs=[TabInfo(target_id='test-0', url='https://example.com', title='Test')],
			screenshot=None,
			dom_state=SerializedDOMState(_root=None, selector_map={}),
		)

		# Test PNG
		read_state_images_png = [{'name': 'test.png', 'data': 'data'}]
		prompt_png = AgentMessagePrompt(
			browser_state_summary=browser_state,
			file_system=fs,
			read_state_images=read_state_images_png,
		)
		message_png = prompt_png.get_user_message(use_vision=True)
		image_parts_png = [part for part in message_png.content if isinstance(part, ContentPartImageParam)]
		assert 'data:image/png;base64' in image_parts_png[0].image_url.url

		# Test JPG
		read_state_images_jpg = [{'name': 'photo.jpg', 'data': 'data'}]
		prompt_jpg = AgentMessagePrompt(
			browser_state_summary=browser_state,
			file_system=fs,
			read_state_images=read_state_images_jpg,
		)
		message_jpg = prompt_jpg.get_user_message(use_vision=True)
		image_parts_jpg = [part for part in message_jpg.content if isinstance(part, ContentPartImageParam)]
		assert 'data:image/jpeg;base64' in image_parts_jpg[0].image_url.url

	def test_agent_message_prompt_no_images(self, tmp_path: Path):
		"""Test that message works correctly when no images are present."""
		fs = FileSystem(tmp_path)

		browser_state = BrowserStateSummary(
			url='https://example.com',
			title='Test',
			tabs=[TabInfo(target_id='test-0', url='https://example.com', title='Test')],
			screenshot=None,
			dom_state=SerializedDOMState(_root=None, selector_map={}),
		)

		# No images
		prompt = AgentMessagePrompt(
			browser_state_summary=browser_state,
			file_system=fs,
			read_state_images=[],
		)

		# Get user message without vision
		user_message = prompt.get_user_message(use_vision=False)

		# Should be plain text, not content parts
		assert isinstance(user_message.content, str)

	def test_agent_message_prompt_empty_base64_skipped(self, tmp_path: Path):
		"""Test that images with empty base64 data are skipped."""
		fs = FileSystem(tmp_path)

		browser_state = BrowserStateSummary(
			url='https://example.com',
			title='Test',
			tabs=[TabInfo(target_id='test-0', url='https://example.com', title='Test')],
			screenshot=None,
			dom_state=SerializedDOMState(_root=None, selector_map={}),
		)

		# Image with empty data field
		read_state_images = [
			{'name': 'empty.png', 'data': ''},  # Empty - should be skipped
			{'name': 'valid.png', 'data': 'valid_data'},  # Valid
		]

		prompt = AgentMessagePrompt(
			browser_state_summary=browser_state,
			file_system=fs,
			read_state_images=read_state_images,
		)

		user_message = prompt.get_user_message(use_vision=True)
		image_parts = [part for part in user_message.content if isinstance(part, ContentPartImageParam)]

		# Should only have 1 image (the valid one)
		assert len(image_parts) == 1
		assert 'valid_data' in image_parts[0].image_url.url


class TestDocxInLLMMessages:
	"""Test that DOCX content flows correctly through to LLM messages."""

	@pytest.mark.asyncio
	async def test_docx_in_extracted_content(self, tmp_path: Path):
		"""Test that DOCX text appears in extracted_content."""
		fs = FileSystem(tmp_path)

		# Create DOCX file
		content = """# Title
Some important content here."""
		await fs.write_file('test.docx', content)

		# Read it
		result = await fs.read_file('test.docx')

		# Verify content is in the result
		assert 'Title' in result
		assert 'important content' in result

	@pytest.mark.asyncio
	async def test_docx_in_message_manager(self, tmp_path: Path):
		"""Test that DOCX content appears in message manager state."""
		fs = FileSystem(tmp_path)
		system_message = SystemMessage(content='Test system message')
		mm = MessageManager(task='test', system_message=system_message, file_system=fs)

		# Simulate read_file action result
		docx_content = """Read from file test.docx.
<content>
Title
Some content here.
</content>"""

		action_results = [
			ActionResult(
				extracted_content=docx_content,
				long_term_memory='Read file test.docx',
				include_extracted_content_only_once=True,
			)
		]

		step_info = AgentStepInfo(step_number=1, max_steps=10)
		mm._update_agent_history_description(model_output=None, result=action_results, step_info=step_info)

		# Verify it's in read_state_description
		assert 'Title' in mm.state.read_state_description
		assert 'Some content' in mm.state.read_state_description


class TestEndToEndIntegration:
	"""End-to-end tests for file reading and LLM message creation."""

	def create_test_image(self) -> bytes:
		"""Create a test image."""
		img = Image.new('RGB', (50, 50), color='blue')
		buffer = io.BytesIO()
		img.save(buffer, format='PNG')
		buffer.seek(0)
		return buffer.read()

	@pytest.mark.asyncio
	async def test_image_end_to_end(self, tmp_path: Path):
		"""Test complete flow: external image → FileSystem → ActionResult → MessageManager → Prompt."""
		# Step 1: Create external image
		external_file = tmp_path / 'photo.png'
		img_bytes = self.create_test_image()
		external_file.write_bytes(img_bytes)

		# Step 2: Read via FileSystem
		fs = FileSystem(tmp_path / 'workspace')
		structured_result = await fs.read_file_structured(str(external_file), external_file=True)

		assert structured_result['images'] is not None

		# Step 3: Create ActionResult (simulating tools/service.py)
		action_result = ActionResult(
			extracted_content=structured_result['message'],
			long_term_memory='Read image file photo.png',
			images=structured_result['images'],
			include_extracted_content_only_once=True,
		)

		# Step 4: Process in MessageManager
		system_message = SystemMessage(content='Test system message')
		mm = MessageManager(task='test', system_message=system_message, file_system=fs)
		step_info = AgentStepInfo(step_number=1, max_steps=10)
		mm._update_agent_history_description(model_output=None, result=[action_result], step_info=step_info)

		# Verify images stored
		assert len(mm.state.read_state_images) == 1
		assert mm.state.read_state_images[0]['name'] == 'photo.png'

		# Step 5: Create message with AgentMessagePrompt
		browser_state = BrowserStateSummary(
			url='https://example.com',
			title='Test',
			tabs=[TabInfo(target_id='test-0', url='https://example.com', title='Test')],
			screenshot=None,
			dom_state=SerializedDOMState(_root=None, selector_map={}),
		)

		prompt = AgentMessagePrompt(
			browser_state_summary=browser_state,
			file_system=fs,
			read_state_images=mm.state.read_state_images,
		)

		user_message = prompt.get_user_message(use_vision=True)

		# Verify image is in message
		assert isinstance(user_message.content, list)
		image_parts = [part for part in user_message.content if isinstance(part, ContentPartImageParam)]
		assert len(image_parts) >= 1

		# Verify image data is correct
		base64_str = base64.b64encode(img_bytes).decode('utf-8')
		assert base64_str in image_parts[0].image_url.url

	@pytest.mark.asyncio
	async def test_docx_end_to_end(self, tmp_path: Path):
		"""Test complete flow: DOCX file → FileSystem → ActionResult → MessageManager."""
		# Step 1: Create DOCX
		fs = FileSystem(tmp_path)
		docx_content = """# Important Document
This is critical information."""

		await fs.write_file('important.docx', docx_content)

		# Step 2: Read it
		read_result = await fs.read_file('important.docx')

		# Step 3: Create ActionResult (simulating tools/service.py)
		action_result = ActionResult(
			extracted_content=read_result,
			long_term_memory=read_result[:100] if len(read_result) > 100 else read_result,
			include_extracted_content_only_once=True,
		)

		# Step 4: Process in MessageManager
		system_message = SystemMessage(content='Test system message')
		mm = MessageManager(task='test', system_message=system_message, file_system=fs)
		step_info = AgentStepInfo(step_number=1, max_steps=10)
		mm._update_agent_history_description(model_output=None, result=[action_result], step_info=step_info)

		# Verify content is in read_state
		assert 'Important Document' in mm.state.read_state_description
		assert 'critical information' in mm.state.read_state_description


if __name__ == '__main__':
	pytest.main([__file__, '-v'])
