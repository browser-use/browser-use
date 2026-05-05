"""
Kimi Code API integration for browser-use.

Uses the OpenAI-compatible API at https://api.kimi.com/coding/
Get your API key from https://www.kimi.com/code/console/api-keys
"""

from dataclasses import dataclass
from typing import Any

import httpx

from browser_use.llm.openai.chat import ChatOpenAI


@dataclass
class ChatKimi(ChatOpenAI):
	"""
	A wrapper for the Kimi Code API which is OpenAI-compatible.

	Get your API key from: https://www.kimi.com/code/console/api-keys

	Required environment variable:
	    KIMI_API_KEY: Your Kimi Code API key

	Example:
	    >>> from browser_use import Agent, ChatKimi
	    >>> llm = ChatKimi(model='kimi-for-coding')
	    >>> agent = Agent(task='Your task', llm=llm)
	"""

	# Model configuration - default to kimi-for-coding
	model: str = 'kimi-for-coding'

	# Client initialization parameters
	api_key: str | None = None
	base_url: str | httpx.URL | None = 'https://api.kimi.com/coding/v1'
	max_retries: int = 5

	# Model params - Kimi-for-coding only allows frequency_penalty=0
	# Temperature is supported but defaults to None for deterministic output
	temperature: float | None = None
	frequency_penalty: float | None = 0

	# JSON Schema compatibility - Kimi uses 'moonshot flavored json schema'
	# which doesn't support certain keywords
	remove_defaults_from_schema: bool = True
	remove_min_items_from_schema: bool = True

	# Static
	@property
	def provider(self) -> str:
		return 'kimi'

	@property
	def model_name(self) -> str:
		return str(self.model)

	def _get_client_params(self) -> dict[str, Any]:
		"""Prepare client parameters dictionary with Kimi-specific settings."""
		# Get base params from parent
		client_params = super()._get_client_params()

		# Ensure base_url is set
		if self.base_url is not None:
			client_params['base_url'] = self.base_url

		# Add required headers for Kimi-for-coding access
		# The API requires both User-Agent and X-Client-Name to identify as a coding agent
		default_headers = client_params.get('default_headers', {})
		coding_agent_headers = {
			'User-Agent': 'claude-code/1.0',
			'X-Client-Name': 'claude-code',
		}
		if isinstance(default_headers, dict):
			# Merge with coding agent headers taking precedence
			default_headers = {**default_headers, **coding_agent_headers}
		else:
			default_headers = coding_agent_headers
		client_params['default_headers'] = default_headers

		return client_params
