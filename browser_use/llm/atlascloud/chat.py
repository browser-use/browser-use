import os
from dataclasses import dataclass

import httpx

from browser_use.llm.openai.chat import ChatOpenAI


@dataclass
class ChatAtlasCloud(ChatOpenAI):
	"""Atlas Cloud chat model using its OpenAI-compatible API."""

	model: str = 'deepseek-ai/deepseek-v4-pro'
	api_key: str | None = None
	base_url: str | httpx.URL | None = 'https://api.atlascloud.ai/v1'
	add_schema_to_system_prompt: bool = True
	dont_force_structured_output: bool = True

	def __post_init__(self) -> None:
		if self.api_key is None:
			self.api_key = os.getenv('ATLASCLOUD_API_KEY')

	@property
	def provider(self) -> str:
		return 'atlascloud'
