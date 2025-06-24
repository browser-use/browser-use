import asyncio
import base64
import io
import random

from lmnr import Laminar
from PIL import Image, ImageDraw, ImageFont

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.google.serializer import GoogleMessageSerializer
from browser_use.llm.messages import (
	BaseMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	ImageURL,
	SystemMessage,
	UserMessage,
)
from browser_use.llm.openai.chat import ChatOpenAI

Laminar.initialize()


def create_random_text_image(text: str = 'hello world', width: int = 4000, height: int = 4000) -> str:
	# Create image with random background color
	bg_color = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
	image = Image.new('RGB', (width, height), bg_color)
	draw = ImageDraw.Draw(image)

	# Try to use a default font, fallback to default if not available
	try:
		font = ImageFont.truetype('arial.ttf', 24)
	except Exception:
		font = ImageFont.load_default()

	# Calculate text position to center it
	bbox = draw.textbbox((0, 0), text, font=font)
	text_width = bbox[2] - bbox[0]
	text_height = bbox[3] - bbox[1]
	x = (width - text_width) // 2
	y = (height - text_height) // 2

	# Draw text with contrasting color
	text_color = (255 - bg_color[0], 255 - bg_color[1], 255 - bg_color[2])
	draw.text((x, y), text, fill=text_color, font=font)

	# Convert to base64
	buffer = io.BytesIO()
	image.save(buffer, format='PNG')
	img_data = base64.b64encode(buffer.getvalue()).decode()

	return f'data:image/png;base64,{img_data}'


async def test_gemini_image_vision():
	"""Test Gemini's ability to see and describe images."""

	# Create the LLM
	llm = ChatGoogle(model='gemini-2.0-flash-exp')
	llm = ChatAnthropic('claude-3-5-sonnet-latest')
	llm = ChatOpenAI(model='gpt-4.1')

	# Create a random image with text
	image_data_url = create_random_text_image('Hello Gemini! Can you see this text?')

	# Create messages with image
	messages: list[BaseMessage] = [
		SystemMessage(content='You are a helpful assistant that can see and describe images.'),
		UserMessage(
			content=[
				ContentPartTextParam(text='What do you see in this image? Please describe the text and any visual elements.'),
				ContentPartImageParam(image_url=ImageURL(url=image_data_url)),
			]
		),
	]

	# Serialize messages for Google format
	serializer = GoogleMessageSerializer()
	formatted_messages, system_message = serializer.serialize_messages(messages)

	print('Testing Gemini image vision...')
	print(f'System message: {system_message}')

	# Make the API call
	try:
		response = await llm.ainvoke(messages)
		print('\n=== Gemini Response ===')
		print(response.completion)
		print(response.usage)
		print('=======================')
	except Exception as e:
		print(f'Error calling Gemini: {e}')
		print(f'Error type: {type(e)}')


if __name__ == '__main__':
	asyncio.run(test_gemini_image_vision())
