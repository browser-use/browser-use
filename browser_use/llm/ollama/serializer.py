import asyncio
import base64
import ipaddress
import json
import socket
from typing import Any, overload
from urllib.parse import urlsplit

import httpx
from ollama._types import Image, Message

from browser_use.llm.messages import (
	AssistantMessage,
	BaseMessage,
	SystemMessage,
	ToolCall,
	UserMessage,
)


class OllamaMessageSerializer:
	"""Serializer for converting between custom message types and Ollama message types."""

	@staticmethod
	def _extract_text_content(content: Any) -> str:
		"""Extract text content from message content, ignoring images."""
		if content is None:
			return ''
		if isinstance(content, str):
			return content

		text_parts: list[str] = []
		for part in content:
			if hasattr(part, 'type'):
				if part.type == 'text':
					text_parts.append(part.text)
				elif part.type == 'refusal':
					text_parts.append(f'[Refusal] {part.refusal}')
			# Skip image parts as they're handled separately

		return '\n'.join(text_parts)

	@staticmethod
	async def _is_public_host(host: str) -> bool:
		"""Return whether ``host`` resolves exclusively to public IP addresses."""
		try:
			addresses = await asyncio.to_thread(socket.getaddrinfo, host, None, type=socket.SOCK_STREAM)
		except socket.gaierror as exc:
			raise ValueError(f'Could not resolve image host {host}: {exc}') from exc

		return bool(addresses) and all(ipaddress.ip_address(address[4][0]).is_global for address in addresses)

	@staticmethod
	async def _download_image(url: str) -> bytes:
		"""Download a remote image after rejecting redirects to non-public hosts."""
		async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
			return await OllamaMessageSerializer._download_image_with_client(url, client)

	@staticmethod
	async def _download_image_with_client(url: str, client: httpx.AsyncClient) -> bytes:
		"""Download one image through an already-created client."""
		for _ in range(5):
			parsed = urlsplit(url)
			if parsed.scheme.lower() not in {'http', 'https'} or not parsed.hostname:
				raise ValueError(f'Unsupported image URL format: {url}')
			if not await OllamaMessageSerializer._is_public_host(parsed.hostname):
				raise ValueError(f'Refusing to download image from non-public host: {parsed.hostname}')

			try:
				response = await client.get(url)
			except httpx.HTTPError as exc:
				raise ValueError(f'Failed to download image from {url}: {exc}') from exc

			if response.is_redirect:
				location = response.headers.get('location')
				if not location:
					raise ValueError(f'Image redirect missing location: {url}')
				url = str(response.url.join(location))
				continue

			response.raise_for_status()
			return response.content

		raise ValueError(f'Too many redirects while downloading image from {url}')

	@staticmethod
	async def _extract_images(content: Any) -> list[Image]:
		"""Extract images from message content without blocking the event loop."""
		if content is None or isinstance(content, str):
			return []

		images: list[Image] = []
		for part in content:
			if hasattr(part, 'type') and part.type == 'image_url':
				url = part.image_url.url
				if url.lower().startswith('data:'):
					# Ollama accepts bytes, paths, or raw base64 rather than data URLs.
					_, data = url.split(',', 1)
					images.append(Image(value=base64.b64decode(data)))
				elif url.lower().startswith(('http://', 'https://')):
					images.append(Image(value=await OllamaMessageSerializer._download_image(url)))
				else:
					images.append(Image(value=url))

		return images

	@staticmethod
	def _serialize_tool_calls(tool_calls: list[ToolCall]) -> list[Message.ToolCall]:
		"""Convert browser-use ToolCalls to Ollama ToolCalls."""
		ollama_tool_calls: list[Message.ToolCall] = []

		for tool_call in tool_calls:
			# Parse arguments from JSON string to dict for Ollama
			try:
				arguments_dict = json.loads(tool_call.function.arguments)
			except json.JSONDecodeError:
				# If parsing fails, wrap in a dict
				arguments_dict = {'arguments': tool_call.function.arguments}

			ollama_tool_call = Message.ToolCall(
				function=Message.ToolCall.Function(name=tool_call.function.name, arguments=arguments_dict)
			)
			ollama_tool_calls.append(ollama_tool_call)

		return ollama_tool_calls

	# region - Serialize overloads
	@overload
	@staticmethod
	async def serialize(message: UserMessage) -> Message: ...

	@overload
	@staticmethod
	async def serialize(message: SystemMessage) -> Message: ...

	@overload
	@staticmethod
	async def serialize(message: AssistantMessage) -> Message: ...

	@staticmethod
	async def serialize(message: BaseMessage) -> Message:
		"""Serialize a custom message to an Ollama Message."""

		if isinstance(message, UserMessage):
			text_content = OllamaMessageSerializer._extract_text_content(message.content)
			images = await OllamaMessageSerializer._extract_images(message.content)

			ollama_message = Message(
				role='user',
				content=text_content if text_content else None,
			)

			if images:
				ollama_message.images = images

			return ollama_message

		elif isinstance(message, SystemMessage):
			text_content = OllamaMessageSerializer._extract_text_content(message.content)

			return Message(
				role='system',
				content=text_content if text_content else None,
			)

		elif isinstance(message, AssistantMessage):
			# Handle content
			text_content = None
			if message.content is not None:
				text_content = OllamaMessageSerializer._extract_text_content(message.content)

			ollama_message = Message(
				role='assistant',
				content=text_content if text_content else None,
			)

			# Handle tool calls
			if message.tool_calls:
				ollama_message.tool_calls = OllamaMessageSerializer._serialize_tool_calls(message.tool_calls)

			return ollama_message

		else:
			raise ValueError(f'Unknown message type: {type(message)}')

	@staticmethod
	async def serialize_messages(messages: list[BaseMessage]) -> list[Message]:
		"""Serialize a list of browser_use messages to Ollama Messages."""
		return [await OllamaMessageSerializer.serialize(message) for message in messages]
