"""
Show how to use sample_images to add image context for your task
"""

import asyncio
import base64
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from browser_use import Agent
from browser_use.llm import ChatOpenAI
from browser_use.llm.messages import ContentPartImageParam, ContentPartTextParam, ImageURL

# Load environment variables
load_dotenv()


def image_to_base64(image_path: str) -> str:
	"""
	Convert image file to base64 string.

	Args:
	    image_path: Path to the image file

	Returns:
	    Base64 encoded string of the image

	Raises:
	    FileNotFoundError: If image file doesn't exist
	    IOError: If image file cannot be read
	"""
	image_file = Path(image_path)
	if not image_file.exists():
		raise FileNotFoundError(f'Image file not found: {image_path}')

	try:
		with open(image_file, 'rb') as f:
			encoded_string = base64.b64encode(f.read())
			return encoded_string.decode('utf-8')
	except OSError as e:
		raise OSError(f'Failed to read image file: {e}')


def create_sample_images() -> list[ContentPartTextParam | ContentPartImageParam]:
	"""
	Create image context for the agent.

	Returns:
	    list of content parts containing text and image data
	"""
	# Image path - replace with your actual image path
	image_path = 'sample_image.png'

	# Image context configuration
	image_context: list[dict[str, Any]] = [
		{
			'type': 'text',
			'value': (
				'The following image explains the google layout. '
				'The image highlights several buttons with red boxes, '
				'and next to them are corresponding labels in red text.\n'
				'Each label corresponds to a button as follows:\n'
				'Label 1 is the "image" button.'
			),
		},
		{'type': 'image', 'value': image_to_base64(image_path)},
	]

	# Convert to content parts
	content_parts = []
	for item in image_context:
		if item['type'] == 'text':
			content_parts.append(ContentPartTextParam(text=item['value']))
		elif item['type'] == 'image':
			content_parts.append(
				ContentPartImageParam(
					image_url=ImageURL(
						url=f'data:image/jpeg;base64,{item["value"]}',
						media_type='image/jpeg',
					),
				)
			)

	return content_parts


async def main() -> None:
	"""
	Main function to run the browser agent with image context.
	"""
	# Task configuration
	task_str = 'goto https://www.google.com/ and click image button'

	# Initialize the language model
	model = ChatOpenAI(model='gpt-4.1')

	# Create sample images for context
	try:
		sample_images = create_sample_images()
	except (FileNotFoundError, OSError) as e:
		print(f'Error loading sample images: {e}')
		print('Continuing without sample images...')
		sample_images = []

	# Initialize and run the agent
	agent = Agent(task=task_str, llm=model, sample_images=sample_images)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
