import os
from dataclasses import dataclass, field

import httpx

from browser_use.llm.openai.like import ChatOpenAILike


@dataclass
class ChatTrustedRouter(ChatOpenAILike):
	"""
	A wrapper around TrustedRouter's chat API, an attested OpenAI-compatible router
	with automatic model selection, zero-data-retention routes, and end-to-end
	encrypted routes.

	This class implements the BaseChatModel protocol for TrustedRouter's API.

	Args:
	    model (str): The TrustedRouter model or routing alias to use
	        (e.g. "trustedrouter/auto", "trustedrouter/zdr", "trustedrouter/e2e").
	    api_key (Optional[str]): The API key to use. Defaults to the
	        TRUSTEDROUTER_API_KEY environment variable.
	"""

	# Model configuration
	model: str = 'trustedrouter/auto'

	# Client initialization parameters
	api_key: str | None = field(default_factory=lambda: os.getenv('TRUSTEDROUTER_API_KEY'))
	base_url: str | httpx.URL | None = 'https://api.trustedrouter.com/v1'

	@property
	def provider(self) -> str:
		return 'trustedrouter'
