import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
from openai import AsyncAzureOpenAI as AsyncAzureOpenAIClient
from openai.types.shared import ChatModel

from browser_use.llm.openai.like import ChatOpenAILike


@dataclass
class ChatAzureOpenAI(ChatOpenAILike):
	"""
	A class for to interact with any provider using the OpenAI API schema.

	Args:
	    model (str): The name of the OpenAI model to use. Defaults to "not-provided".
	    api_key (Optional[str]): The API key to use. Defaults to "not-provided".
	"""

	# Model configuration
	model: str | ChatModel

	# Client initialization parameters
	api_key: Optional[str] = None
	api_version: Optional[str] = '2024-10-21'
	azure_endpoint: Optional[str] = None
	azure_deployment: Optional[str] = None
	base_url: Optional[str] = None
	azure_ad_token: Optional[str] = None
	azure_ad_token_provider: Optional[Any] = None

	default_headers: Optional[Dict[str, str]] = None
	default_query: Optional[Dict[str, Any]] = None

	client: Optional[AsyncAzureOpenAIClient] = None

	@property
	def provider(self) -> str:
		return 'azure'

	def _get_client_params(self) -> Dict[str, Any]:
		_client_params: Dict[str, Any] = {}

		self.api_key = self.api_key or os.getenv('AZURE_OPENAI_API_KEY')
		self.azure_endpoint = self.azure_endpoint or os.getenv('AZURE_OPENAI_ENDPOINT')
		self.azure_deployment = self.azure_deployment or os.getenv('AZURE_OPENAI_DEPLOYMENT')
		params_mapping = {
			'api_key': self.api_key,
			'api_version': self.api_version,
			'organization': self.organization,
			'azure_endpoint': self.azure_endpoint,
			'azure_deployment': self.azure_deployment,
			'base_url': self.base_url,
			'azure_ad_token': self.azure_ad_token,
			'azure_ad_token_provider': self.azure_ad_token_provider,
			'http_client': self.http_client,
		}
		if self.default_headers is not None:
			_client_params['default_headers'] = self.default_headers
		if self.default_query is not None:
			_client_params['default_query'] = self.default_query

		_client_params.update({k: v for k, v in params_mapping.items() if v is not None})

		return _client_params

	def get_client(self) -> AsyncAzureOpenAIClient:
		"""
		Returns an asynchronous OpenAI client.

		Returns:
			AsyncAzureOpenAIClient: An instance of the asynchronous OpenAI client.
		"""
		if self.client:
			return self.client

		_client_params: Dict[str, Any] = self._get_client_params()

		if self.http_client:
			_client_params['http_client'] = self.http_client
		else:
			# Create a new async HTTP client with custom limits
			_client_params['http_client'] = httpx.AsyncClient(
				limits=httpx.Limits(max_connections=1000, max_keepalive_connections=100)
			)

		self.client = AsyncAzureOpenAIClient(**_client_params)

		return self.client
