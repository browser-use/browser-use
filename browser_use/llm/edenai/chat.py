import os
from dataclasses import dataclass
from typing import Any

import httpx

from browser_use.llm.openai.like import ChatOpenAILike


@dataclass
class ChatEdenAI(ChatOpenAILike):
	"""
	A class for interacting with Eden AI using the OpenAI-compatible API schema.

	Eden AI (https://www.edenai.co) is an EU-based, OpenAI-compatible LLM gateway.
	A single API key reaches models from many providers with vendor-prefixed ids,
	e.g. 'openai/gpt-4o-mini', 'anthropic/claude-sonnet-4-5' or
	'mistral/mistral-large-latest'.

	Reads `EDENAI_API_KEY` when `api_key` is not set. For EU data residency, set
	`base_url='https://api.eu.edenai.run/v3'`.

	Args:
		model (str): The Eden AI model id to use. Defaults to 'openai/gpt-4o-mini'.
		api_key (str | None): Eden AI API key. Falls back to the EDENAI_API_KEY env var.
		base_url (str | httpx.URL | None): Eden AI base url. Defaults to the global
			endpoint 'https://api.edenai.run/v3'.
	"""

	model: str = 'openai/gpt-4o-mini'
	base_url: str | httpx.URL | None = 'https://api.edenai.run/v3'

	@property
	def provider(self) -> str:
		return 'edenai'

	def _get_client_params(self) -> dict[str, Any]:
		self.api_key = self.api_key or os.getenv('EDENAI_API_KEY')
		return super()._get_client_params()
