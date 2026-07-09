import os
from dataclasses import dataclass

import httpx

from browser_use.llm.openai.chat import ChatOpenAI


@dataclass
class ChatMiniMax(ChatOpenAI):
	"""
	MiniMax chat model using MiniMax's OpenAI-compatible API.

	MiniMax-M3 supports the existing OpenAI-style multimodal message format used by
	Browser Use for screenshots and target/sample images.
	"""

	model: str = 'MiniMax-M3'
	api_key: str | None = None
	base_url: str | httpx.URL | None = 'https://api.minimax.io/v1'
	max_completion_tokens: int | None = 4096

	def __post_init__(self) -> None:
		if self.api_key is None:
			self.api_key = os.getenv('MINIMAX_API_KEY')

	@property
	def provider(self) -> str:
		return 'minimax'
