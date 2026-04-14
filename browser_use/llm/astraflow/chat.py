from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from browser_use.llm.openai.chat import ChatOpenAI


@dataclass
class ChatAstraflow(ChatOpenAI):
	"""
	Astraflow (UCloud ModelVerse) global endpoint wrapper.

	Uses the OpenAI-compatible API at https://api-us-ca.umodelverse.ai/v1.
	Set the ASTRAFLOW_API_KEY environment variable with your API key.

	Supported models include:
	  - deepseek-r1
	  - deepseek-v3
	  - llama-3.3-70b-instruct
	"""

	model: str = 'deepseek-v3'
	base_url: str | httpx.URL | None = 'https://api-us-ca.umodelverse.ai/v1'

	# Astraflow does not advertise support for frequency_penalty;
	# set to None to avoid potential 422 errors on the provider side.
	frequency_penalty: float | None = None

	@property
	def provider(self) -> str:
		return 'astraflow'


@dataclass
class ChatAstraflowCN(ChatOpenAI):
	"""
	Astraflow (UCloud ModelVerse) China endpoint wrapper.

	Uses the OpenAI-compatible API at https://api.umodelverse.ai/v1.
	Set the ASTRAFLOW_CN_API_KEY environment variable with your API key.

	Supported models include:
	  - deepseek-r1
	  - deepseek-v3
	  - llama-3.3-70b-instruct
	"""

	model: str = 'deepseek-v3'
	base_url: str | httpx.URL | None = 'https://api.umodelverse.ai/v1'

	frequency_penalty: float | None = None

	@property
	def provider(self) -> str:
		return 'astraflow-cn'
