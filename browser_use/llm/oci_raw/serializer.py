"""
Message serializer for OCI Raw API integration.

This module handles the conversion between browser-use message formats
and the OCI Raw API message format using proper OCI SDK models.
"""

from oci.generative_ai_inference.models import ImageContent, ImageUrl, Message, TextContent

from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	ContentPartImageParam,
	SystemMessage,
	UserMessage,
)


class OCIRawMessageSerializer:
	"""
	Serializer for converting between browser-use message types and OCI Raw API message formats.
	Uses proper OCI SDK model objects as shown in the working example.

	Supports both:
	- GenericChatRequest (Meta, xAI models) - uses messages array
	- CohereChatRequest (Cohere models) - uses single message string
	"""

	@staticmethod
	def _is_base64_image(url: str) -> bool:
		"""Check if the URL is a base64 encoded image."""
		return url.startswith('data:image/')

	@staticmethod
	def _parse_base64_url(url: str) -> str:
		"""Parse base64 URL and return the base64 data."""
		if not OCIRawMessageSerializer._is_base64_image(url):
			raise ValueError(f'Not a base64 image URL: {url}')

		# Extract the base64 data from data:image/png;base64,<data>
		try:
			header, data = url.split(',', 1)
			return data
		except ValueError:
			raise ValueError(f'Invalid base64 image URL format: {url}')

	@staticmethod
	def _create_image_content(part: ContentPartImageParam) -> ImageContent:
		"""Convert ContentPartImageParam to OCI ImageContent."""
		url = part.image_url.url

		if OCIRawMessageSerializer._is_base64_image(url):
			# Handle base64 encoded images - OCI expects data URLs as-is
			image_url = ImageUrl(url=url)
		else:
			# Handle regular URLs
			image_url = ImageUrl(url=url)

		return ImageContent(image_url=image_url)

	@staticmethod
	def serialize_messages(messages: list[BaseMessage]) -> list[Message]:
		"""
		Serialize a list of browser-use messages to OCI Raw API Message objects.

		Args:
		    messages: List of browser-use messages

		Returns:
		    List of OCI Message objects
		"""
		oci_messages = []

		for message in messages:
			oci_message = Message()

			if isinstance(message, UserMessage):
				oci_message.role = 'USER'
				content = message.content
				if isinstance(content, str):
					text_content = TextContent()
					text_content.text = content
					oci_message.content = [text_content]
				elif isinstance(content, list):
					# Handle content parts - text and images
					contents = []
					for part in content:
						if part.type == 'text':
							text_content = TextContent()
							text_content.text = part.text
							contents.append(text_content)
						elif part.type == 'image_url':
							image_content = OCIRawMessageSerializer._create_image_content(part)
							contents.append(image_content)
					if contents:
						oci_message.content = contents

			elif isinstance(message, SystemMessage):
				oci_message.role = 'SYSTEM'
				content = message.content
				if isinstance(content, str):
					text_content = TextContent()
					text_content.text = content
					oci_message.content = [text_content]
				elif isinstance(content, list):
					# Handle content parts - typically just text for system messages
					contents = []
					for part in content:
						if part.type == 'text':
							text_content = TextContent()
							text_content.text = part.text
							contents.append(text_content)
						elif part.type == 'image_url':
							# System messages can theoretically have images too
							image_content = OCIRawMessageSerializer._create_image_content(part)
							contents.append(image_content)
					if contents:
						oci_message.content = contents

			elif isinstance(message, AssistantMessage):
				oci_message.role = 'ASSISTANT'
				content = message.content
				if isinstance(content, str):
					text_content = TextContent()
					text_content.text = content
					oci_message.content = [text_content]
				elif isinstance(content, list):
					# Handle content parts - text, images, and refusals
					contents = []
					for part in content:
						if part.type == 'text':
							text_content = TextContent()
							text_content.text = part.text
							contents.append(text_content)
						elif part.type == 'image_url':
							# Assistant messages can have images in responses
							# Note: This is currently unreachable in browser-use but kept for completeness
							image_content = OCIRawMessageSerializer._create_image_content(part)
							contents.append(image_content)
						elif part.type == 'refusal':
							text_content = TextContent()
							text_content.text = f'[Refusal] {part.refusal}'
							contents.append(text_content)
					if contents:
						oci_message.content = contents
			else:
				# Fallback for any message format issues
				oci_message.role = 'USER'
				text_content = TextContent()
				text_content.text = str(message)
				oci_message.content = [text_content]

			# Only append messages that have content
			if hasattr(oci_message, 'content') and oci_message.content:
				oci_messages.append(oci_message)

		return oci_messages

	@staticmethod
	def serialize_messages_for_cohere(messages: list[BaseMessage]) -> str:
		"""
		Serialize messages for Cohere models which expect a single message string.

		Cohere models use CohereChatRequest.message (string) instead of messages array.
		We combine all messages into a single conversation string.

		Args:
		    messages: List of browser-use messages

		Returns:
		    Single string containing the conversation
		"""
		conversation_parts = []

		for message in messages:
			content = ''

			if isinstance(message, UserMessage):
				if isinstance(message.content, str):
					content = message.content
				elif isinstance(message.content, list):
					# Extract text from content parts
					text_parts = []
					for part in message.content:
						if part.type == 'text':
							text_parts.append(part.text)
						elif part.type == 'image_url':
							# Cohere may not support images in all models, use a short placeholder
							# to avoid massive token usage from base64 data URIs
							if part.image_url.url.startswith('data:image/'):
								text_parts.append('[Image: base64_data]')
							else:
								text_parts.append('[Image: external_url]')
					content = ' '.join(text_parts)

				conversation_parts.append(f'User: {content}')

			elif isinstance(message, SystemMessage):
				if isinstance(message.content, str):
					content = message.content
				elif isinstance(message.content, list):
					# Extract text from content parts
					text_parts = []
					for part in message.content:
						if part.type == 'text':
							text_parts.append(part.text)
					content = ' '.join(text_parts)

				conversation_parts.append(f'System: {content}')

			elif isinstance(message, AssistantMessage):
				if isinstance(message.content, str):
					content = message.content
				elif isinstance(message.content, list):
					# Extract text from content parts
					text_parts = []
					for part in message.content:
						if part.type == 'text':
							text_parts.append(part.text)
						elif part.type == 'refusal':
							text_parts.append(f'[Refusal] {part.refusal}')
					content = ' '.join(text_parts)

				conversation_parts.append(f'Assistant: {content}')
			else:
				# Fallback
				conversation_parts.append(f'User: {str(message)}')

		return '\n\n'.join(conversation_parts)
