import os
from dataclasses import dataclass

from browser_use.llm.openai.like import ChatOpenAILike


@dataclass
class ChatAtlasCloud(ChatOpenAILike):
	"""
	A class for interacting with Atlas Cloud models using the OpenAI-compatible API.

	Atlas Cloud (https://www.atlascloud.ai) exposes an OpenAI-compatible
	`/v1/chat/completions` endpoint, so this provider reuses the OpenAI client
	and only swaps the base URL, API key and default model.

	Args:
	    model (str): The Atlas Cloud model to use, e.g. ``deepseek-ai/deepseek-v4-pro``.
	    api_key (Optional[str]): Atlas Cloud API key. Falls back to the
	        ``ATLASCLOUD_API_KEY`` environment variable.
	    base_url (str): The Atlas Cloud API base URL. Defaults to
	        ``https://api.atlascloud.ai/v1`` (or the ``ATLASCLOUD_API_BASE`` env var).
	"""

	# Model configuration
	model: str = 'deepseek-ai/deepseek-v4-pro'

	# Client initialization parameters
	api_key: str | None = None
	base_url: str = 'https://api.atlascloud.ai/v1'

	@property
	def provider(self) -> str:
		return 'atlascloud'

	def _get_client_params(self):
		# Resolve credentials/base URL from the environment if not explicitly set.
		self.api_key = self.api_key or os.getenv('ATLASCLOUD_API_KEY')
		self.base_url = os.getenv('ATLASCLOUD_API_BASE') or self.base_url
		return super()._get_client_params()
