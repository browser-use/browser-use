"""Models. Default: bu-ultrafast on the Browser Use gateway (one Browser Use API key runs model and browser).

ChatBrowserUse  the gateway (OpenAI-compatible chat completions)
ChatOpenAI      api.openai.com -> Responses API (the evaluated setup); any other base_url -> chat completions
ChatAnthropic   needs `browser-use[anthropic]`
ChatGoogle      needs `browser-use[google]`

Any Pydantic AI model string ('openai:gpt-6-luna', 'anthropic:claude-...', 'google-gla:gemini-...') or Model works too.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from browser_use.auth import browser_use_api_key

GATEWAY_URL = 'https://api.browser-use.com/api/llm/v1'
BILLING_URL = 'https://cloud.browser-use.com/settings?tab=billing'
DEFAULT_MODEL = 'bu-ultrafast'  # gpt-6-luna, low reasoning, priority tier. bu-auto: same model, medium, default tier
EXTRAS = {'anthropic': 'anthropic', 'google-gla': 'google', 'google-vertex': 'google', 'google': 'google'}


def compatible_profile() -> Any:
	"""Profile override for OpenAI-compatible chat servers. allowed_tools is an OpenAI-only tool_choice that vLLM and
	DeepSeek reject and Ollama ignores; without it Pydantic AI narrows the tool list and sends plain 'required'.
	Strict tool definitions are an OpenAI feature too (Pydantic AI's Ollama profile turns them off): never sent here."""
	from pydantic_ai.profiles.openai import OpenAIModelProfile

	return OpenAIModelProfile(openai_chat_supports_allowed_tools=False, openai_supports_strict_tool_definition=False)


class ChatBrowserUse:
	"""Browser Use gateway models ('bu-ultrafast', 'bu-auto', 'bu-smart', ...). Key: BROWSER_USE_API_KEY or `browser-use login`."""

	provider = 'browser-use'

	def __init__(self, model: str = DEFAULT_MODEL, *, api_key: str | None = None, base_url: Any = GATEWAY_URL):
		self.model, self.api_key, self.base_url = model, api_key, str(base_url)

	def pydantic_model(self) -> Any:
		from pydantic_ai.models.openai import OpenAIChatModel
		from pydantic_ai.providers.openai import OpenAIProvider

		key = self.api_key or browser_use_api_key(f'The default model ({self.model})')
		provider = OpenAIProvider(base_url=self.base_url, api_key=key)
		return OpenAIChatModel(self.model, provider=provider, profile=compatible_profile())

	def model_settings(self) -> dict:
		return {}

	def explain_error(self, e: Exception) -> str | None:
		"""One actionable line for gateway HTTP errors. The gateway's own message wins: it names the actual cause."""
		status = getattr(e, 'status_code', None)
		code = getattr(e, 'provider_error_code', None)
		body = getattr(e, 'body', None)
		message = body.get('message') if isinstance(body, dict) else None
		if status == 401:
			return 'Browser Use API key rejected (401). Run `browser-use login` or check BROWSER_USE_API_KEY.'
		if status == 402:
			return f'Out of Browser Use credits (402): add credits at {BILLING_URL}'
		if status == 403:
			if code == 'insufficient_scope':
				return f'{message or "This API key cannot use the gateway (403)."} Run `browser-use login` again for a new key.'
			if message:
				return f'{self.model} is not available for this key (403): {message}'
			return (
				f'{self.model} is not available for this account (403). '
				'Use your own model meanwhile, e.g. llm=ChatOpenAI("gpt-6-luna").'
			)
		if status == 404:
			return f'{self.model} is not on the Browser Use gateway (404). Check the model id or use llm=ChatOpenAI(...).'
		return None


class ChatOpenAI:
	"""OpenAI, or any OpenAI-compatible server via base_url (DeepSeek, vLLM, Ollama, OpenRouter, ...)."""

	provider = 'openai'

	def __init__(
		self,
		model: str,
		*,
		api_key: str | None = None,
		base_url: Any = None,
		temperature: float | None = None,
		reasoning_effort: str | None = None,
	):
		"""base_url: str or URL object (httpx.URL). reasoning_effort: sent as-is (reasoning_effort on chat backends)."""
		self.model, self.api_key = model, api_key
		self.base_url = None if base_url is None else str(base_url)
		self.temperature, self.reasoning_effort = temperature, reasoning_effort

	@property
	def is_official(self) -> bool:
		"""api.openai.com, judged by the hostname of the URL the client will use (base_url, else OPENAI_BASE_URL)."""
		url = self.base_url or os.environ.get('OPENAI_BASE_URL')
		return not url or urlparse(url).hostname == 'api.openai.com'

	def pydantic_model(self) -> Any:
		from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
		from pydantic_ai.providers.openai import OpenAIProvider

		provider = OpenAIProvider(api_key=self.api_key, base_url=self.base_url)
		if self.is_official:  # Responses API + server-side compaction: what we evaluate
			return OpenAIResponsesModel(self.model, provider=provider)
		return OpenAIChatModel(self.model, provider=provider, profile=compatible_profile())  # no OpenAI-only settings

	def model_settings(self) -> dict:
		settings: dict = {}
		if self.temperature is not None:
			settings['temperature'] = self.temperature
		if self.reasoning_effort is not None:
			settings['openai_reasoning_effort'] = self.reasoning_effort
		return settings


class ChatAnthropic:
	provider = 'anthropic'

	def __init__(self, model: str, *, api_key: str | None = None):
		self.model, self.api_key = model, api_key

	def pydantic_model(self) -> Any:
		try:
			from pydantic_ai.models.anthropic import AnthropicModel
			from pydantic_ai.providers.anthropic import AnthropicProvider
		except ImportError:
			raise ImportError(extra_hint('anthropic')) from None
		return AnthropicModel(self.model, provider=AnthropicProvider(api_key=self.api_key))

	def model_settings(self) -> dict:
		return {}


class ChatGoogle:
	provider = 'google'

	def __init__(self, model: str, *, api_key: str | None = None):
		self.model, self.api_key = model, api_key

	def pydantic_model(self) -> Any:
		try:
			from pydantic_ai.models.google import GoogleModel
			from pydantic_ai.providers.google import GoogleProvider
		except ImportError:
			raise ImportError(extra_hint('google')) from None
		return GoogleModel(self.model, provider=GoogleProvider(api_key=self.api_key))

	def model_settings(self) -> dict:
		return {}


CHAT_MODELS = (ChatBrowserUse, ChatOpenAI, ChatAnthropic, ChatGoogle)


def extra_hint(extra: str) -> str:
	if extra in EXTRAS.values():
		return f"This model needs the {extra} extra: pip install 'browser-use[{extra}]'"
	return f"This model needs Pydantic AI's {extra} support: pip install 'pydantic-ai-slim[{extra}]'"


def model_ref(llm: Any) -> Any:
	"""'openai/gpt-5.6-luna' (bu-pi style) -> 'openai-responses:gpt-5.6-luna'. Pydantic AI strings and models pass through."""
	if not isinstance(llm, str) or ':' in llm or '/' not in llm:
		return llm
	provider, name = llm.split('/', 1)
	return f'{"openai-responses" if provider == "openai" else provider}:{name}'


def as_chat_model(llm: Any) -> Any:
	"""None and 'bu-*' strings -> ChatBrowserUse. Everything else is returned unchanged (validated by resolve_model)."""
	if llm is None:
		return ChatBrowserUse()
	if isinstance(llm, str) and llm.startswith('bu-'):
		return ChatBrowserUse(llm)
	return llm


def resolve_model(llm: Any) -> tuple[Any, dict]:
	"""-> (Pydantic AI Model, extra model settings). Raises before any browser starts: missing key, missing extra."""
	from pydantic_ai.models import Model, infer_model

	if isinstance(llm, CHAT_MODELS):
		return llm.pydantic_model(), llm.model_settings()
	if isinstance(llm, Model):
		return llm, {}
	if isinstance(llm, str):
		ref = model_ref(llm)
		try:
			return infer_model(ref), {}
		except ImportError:
			prefix = str(ref).split(':', 1)[0]
			raise ImportError(extra_hint(EXTRAS.get(prefix, prefix))) from None
	raise TypeError(
		f'llm={type(llm).__name__} is not supported in browser-use 1.0. Pass ChatBrowserUse(), ChatOpenAI(...), '
		"ChatAnthropic(...), ChatGoogle(...), a Pydantic AI model string like 'groq:llama-3.3-70b' or a Pydantic AI "
		'Model. See MIGRATING.md.'
	)


__all__ = ['ChatAnthropic', 'ChatBrowserUse', 'ChatGoogle', 'ChatOpenAI', 'GATEWAY_URL', 'model_ref', 'resolve_model']
