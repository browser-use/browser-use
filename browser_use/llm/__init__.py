"""Models. Default: bu-fast on the Browser Use gateway (one Browser Use API key runs model and browser).

ChatBrowserUse  the gateway: stateless OpenAI Responses (store=false, encrypted reasoning) + server-side compaction
ChatOpenAI      api.openai.com -> Responses API (the evaluated setup); the gateway URL -> as ChatBrowserUse;
                any other base_url -> chat completions
ChatAnthropic   Anthropic (built in)
ChatGoogle      Google Gemini (built in)

Any Pydantic AI model string ('openai:gpt-6-luna', 'anthropic:claude-...', 'google:gemini-...') or Model works too.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from pydantic import SecretStr

from browser_use.auth import browser_use_api_key, clean_api_key

GATEWAY_URL = 'https://api.browser-use.com/api/v4/llm/v1'
BILLING_URL = 'https://cloud.browser-use.com/settings?tab=billing'
DEFAULT_MODEL = 'bu-fast'  # gpt-6-luna, medium reasoning, default tier (the evaluated setup). bu-ultrafast: low, priority
GATEWAY_UPSTREAM = {'bu-smart': 'gpt-6.1-sol', 'bu-smart-v1': 'gpt-6.1-sol'}  # other bu-* aliases run gpt-6-luna
LEGACY_MODEL = re.compile(r'bu-(latest|\d+-\d+)\b')  # bu-2-0, bu-1-0, bu-2-0-mini-preview, bu-latest: the 0.x gateway
PREFLIGHT_TIMEOUT_S = 15
GOOGLE_HOST = 'generativelanguage.googleapis.com'
CHAT_REMOVED = (
	'1.0 Chat classes take the model and api_key (ChatOpenAI also base_url, temperature and reasoning_effort); for '
	"other model settings pass a Pydantic AI Model built with settings=..., e.g. llm=AnthropicModel('claude-...', "
	'settings={...}).'
)


def _plain(key: str | SecretStr | None) -> str | None:
	"""A SecretStr key (LangChain-era 0.x code) as the plain string: str() of it is '**********'."""
	return key.get_secret_value() if isinstance(key, SecretStr) else key


def _chat_kwargs(cls: str, kwargs: dict[str, Any]) -> None:
	if kwargs:
		from browser_use.exceptions import removed

		name = next(iter(kwargs))
		instead = "model='bu-ultrafast' (the same model, low reasoning, priority tier)." if name == 'fast' else CHAT_REMOVED
		raise TypeError(removed(f'{cls}({name}=...)', instead))


EXTRAS = {
	'anthropic': 'anthropic',
	'google': 'google',
	'google-cloud': 'google',
	'google-gla': 'google',
	'google-vertex': 'google',
}


def compatible_profile() -> Any:
	"""Profile override for OpenAI-compatible chat servers. allowed_tools is an OpenAI-only tool_choice that vLLM and
	DeepSeek reject and Ollama ignores; without it Pydantic AI narrows the tool list and sends plain 'required'.
	Strict tool definitions are an OpenAI feature too (Pydantic AI's Ollama profile turns them off): never sent here."""
	from pydantic_ai.profiles.openai import OpenAIModelProfile

	return OpenAIModelProfile(openai_chat_supports_allowed_tools=False, openai_supports_strict_tool_definition=False)


def gateway_profile(model: str) -> Any:
	"""The upstream model's OpenAI profile (reasoning, encrypted reasoning) under the gateway's rules: it stores nothing
	(store=false, so reasoning round-trips encrypted and nothing is chained by previous_response_id) and serves no
	hosted tools. The model name sent is unchanged; only request features follow the upstream model."""
	from pydantic_ai.profiles.openai import openai_model_profile

	upstream = GATEWAY_UPSTREAM.get(model, 'gpt-6-luna' if model.startswith('bu-') else model)
	profile = openai_model_profile(upstream) or {}
	return {**profile, 'openai_responses_requires_store_false': True, 'supported_native_tools': frozenset()}


def gateway_model(model: str, api_key: str, base_url: str) -> Any:
	from pydantic_ai.models.openai import OpenAIResponsesModel
	from pydantic_ai.providers.openai import OpenAIProvider

	class GatewayResponsesModel(OpenAIResponsesModel):
		browser_use_llm: ChatBrowserUse | None = None  # Agent: preflight, gateway errors, alias effort, charge-only cost
		# no additional_tools input items or deferred tools: the gateway accepts only function/custom tools and items
		supported_tool_addition_modes = frozenset()
		supported_tool_deferral_modes = frozenset()

		def _process_provider_details(self, response: Any) -> dict[str, Any] | None:
			"""The gateway's final response carries browser_use{resolved_model, service_tier, charge_usd}."""
			meta = (response.model_extra or {}).get('browser_use')
			return {'browser_use': meta} if isinstance(meta, dict) else None

	provider = OpenAIProvider(base_url=base_url, api_key=api_key)
	resolved = GatewayResponsesModel(model, provider=provider, profile=gateway_profile(model))
	resolved.browser_use_llm = ChatBrowserUse(model, api_key=api_key, base_url=base_url)
	return resolved


class ChatBrowserUse:
	"""Browser Use gateway models ('bu-fast', 'bu-ultrafast', 'bu-smart', or a listed OpenAI model such as 'gpt-6.1-sol').
	Key: BROWSER_USE_API_KEY or `browser-use login`. Without Agent(reasoning=...) the alias's own effort applies."""

	provider = 'browser-use'

	def __init__(
		self, model: str = DEFAULT_MODEL, *, api_key: str | SecretStr | None = None, base_url: Any = GATEWAY_URL, **kwargs: Any
	):
		_chat_kwargs('ChatBrowserUse', kwargs)
		if isinstance(model, str) and LEGACY_MODEL.match(model):  # the 0.x gateway's models: the new one answers 404
			raise ValueError(
				f"{model} needs browser-use<1.0 (pip install 'browser-use<1.0'), or use bu-fast with browser-use 1.0."
			)
		key = clean_api_key(plain, 'ChatBrowserUse(api_key=...)', f'The model {model}') if (plain := _plain(api_key)) else None
		self.model, self.api_key, self.base_url = model, key, str(base_url)

	def pydantic_model(self) -> Any:
		key = self.api_key or browser_use_api_key(f'The default model ({self.model})')
		return gateway_model(self.model, key, self.base_url)

	def model_settings(self) -> dict:
		return {}

	def explain_error(self, e: Exception) -> str | None:
		"""One actionable line for gateway HTTP errors. The gateway's own message wins: it names the actual cause."""
		body = getattr(e, 'body', None)
		body = body if isinstance(body, dict) else {}
		code = getattr(e, 'provider_error_code', None) or body.get('code')
		return self._explain(getattr(e, 'status_code', None), code, body.get('message'))

	def _explain(self, status: int | None, code: str | None, message: str | None) -> str | None:
		if code == 'legacy_model' or (status == 400 and LEGACY_MODEL.match(self.model)):
			return f"{self.model} needs browser-use<1.0 (pip install 'browser-use<1.0'), or use bu-fast with browser-use 1.0."
		if status == 400 and code in ('invalid_model', 'model_not_on_gateway'):
			return f'{self.model} is not on the Browser Use gateway (400): {message or "use bu-fast, bu-ultrafast or bu-smart."}'
		if status == 401:
			return 'Browser Use API key rejected (401): check api_key=..., or BROWSER_USE_API_KEY / `browser-use login`.'
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
		if status == 404:  # unknown models are 400s: a 404 is the route itself
			return (
				f'The Browser Use gateway is not deployed at {self.base_url} (404), or base_url is wrong. Use your own '
				'model meanwhile, e.g. llm=ChatOpenAI("gpt-6-luna").'
			)
		return None

	def preflight(self) -> str | None:
		"""GET {base_url}/models (free): a gateway that is not there, a rejected key or a model the gateway does not
		list fails here, before a cloud browser is created and billed. Returns the error line, or None."""
		key = self.api_key or browser_use_api_key(f'The default model ({self.model})')
		url = f'{self.base_url.rstrip("/")}/models'
		request = urllib.request.Request(url, headers={'Authorization': f'Bearer {key}'})
		try:
			with urllib.request.urlopen(request, timeout=PREFLIGHT_TIMEOUT_S) as r:
				listed = {m.get('id') for m in json.loads(r.read()).get('data') or [] if isinstance(m, dict)}
		except urllib.error.HTTPError as e:
			try:
				error = json.loads(e.read()).get('error') or {}
			except (ValueError, AttributeError):  # Go's plain-text 404
				error = {}
			error = error if isinstance(error, dict) else {}
			return self._explain(e.code, error.get('code'), error.get('message')) or (
				f'The Browser Use gateway at {self.base_url} answered HTTP {e.code}: {str(error.get("message") or e.reason)[:300]}'
			)
		except (OSError, ValueError) as e:  # refused, DNS, timeout, not JSON
			return f'The Browser Use gateway at {self.base_url} is not reachable: {e}'
		if not listed or self.model in listed or self.model.removeprefix('openai/') in listed:
			return None
		if LEGACY_MODEL.match(self.model):
			return self._explain(400, 'legacy_model', None)
		return f'{self.model} is not on the Browser Use gateway. Listed: {", ".join(sorted(str(m) for m in listed))}.'


class ChatOpenAI:
	"""OpenAI, or any OpenAI-compatible server via base_url (DeepSeek, vLLM, Ollama, OpenRouter, ...)."""

	provider = 'openai'

	def __init__(
		self,
		model: str,
		*,
		api_key: str | SecretStr | None = None,
		base_url: Any = None,
		temperature: float | None = None,
		reasoning_effort: str | None = None,
		**kwargs: Any,
	):
		"""base_url: str or URL object (httpx.URL). reasoning_effort: sent as-is (reasoning_effort on chat backends)."""
		_chat_kwargs('ChatOpenAI', kwargs)
		self.model, self.api_key = model, _plain(api_key)
		self.base_url = None if base_url is None else str(base_url)
		self.temperature, self.reasoning_effort = temperature, reasoning_effort

	@property
	def url(self) -> str | None:
		"""The URL the client will use: base_url, else OPENAI_BASE_URL."""
		return self.base_url or os.environ.get('OPENAI_BASE_URL')

	@property
	def is_gateway(self) -> bool:
		"""The Browser Use gateway URL (https only, so a Browser Use key never goes out in clear text): served as
		ChatBrowserUse."""
		url, gateway = urlparse(self.url or ''), urlparse(GATEWAY_URL)
		return (url.scheme, url.netloc.lower(), url.path.rstrip('/')) == (gateway.scheme, gateway.netloc, gateway.path)

	@property
	def is_official(self) -> bool:
		"""api.openai.com, judged by the hostname of the URL the client will use."""
		return not self.url or urlparse(self.url).hostname == 'api.openai.com'

	def pydantic_model(self) -> Any:
		from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
		from pydantic_ai.providers.openai import OpenAIProvider

		if self.is_gateway:  # key: api_key, else a Browser Use key in OPENAI_API_KEY (as 0.x), else the Browser Use key
			env = os.environ.get('OPENAI_API_KEY', '')
			key = self.api_key or (env if env.startswith('bu_') else None)
			return ChatBrowserUse(self.model, api_key=key, base_url=self.url).pydantic_model()
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

	def __init__(self, model: str, *, api_key: str | SecretStr | None = None, **kwargs: Any):
		_chat_kwargs('ChatAnthropic', kwargs)
		self.model, self.api_key = model, _plain(api_key)

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

	def __init__(self, model: str, *, api_key: str | SecretStr | None = None, **kwargs: Any):
		_chat_kwargs('ChatGoogle', kwargs)
		self.model, self.api_key = model, _plain(api_key)

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


def skip_responses_transform() -> None:
	"""openai-python rewrites every Responses request body against its TypedDicts before sending it: one async call per
	node and union member, ~20k calls at 50k tokens (~30 ms on an M5 Pro, more on a slower runner), growing with the
	history (bu-pi's Node SDK sends the body as is). That pass only renames aliased keys, formats annotated values and
	drops omitted ones. When the installed openai's create params carry no alias or format, plain JSON bodies are sent
	minus omitted keys: the same bytes. Anything else, or an openai that moved these internals, keeps the SDK's pass."""
	try:
		import openai.resources.responses.responses as responses
		from openai._utils import is_given
		from openai.types.responses import response_create_params as params

		transform = getattr(responses, 'async_maybe_transform')  # module-level, not exported
		create = (params.ResponseCreateParamsNonStreaming, params.ResponseCreateParamsStreaming)
		if getattr(transform, 'skips_create', False) or responses_params_rewrite(*create):
			return
	except (ImportError, AttributeError):
		return

	async def maybe_transform(data: Any, expected_type: Any) -> Any:
		if expected_type in create and isinstance(data, dict):
			body = {k: v for k, v in data.items() if is_given(v)}
			if _json(body):
				return body
		return await transform(data, expected_type)

	maybe_transform.skips_create = True  # type: ignore[attr-defined]
	setattr(responses, 'async_maybe_transform', maybe_transform)


def responses_params_rewrite(*types: Any) -> bool:
	"""True when any field reachable from these openai TypedDicts has an alias or format, i.e. the SDK pass changes bytes."""
	import typing

	import typing_extensions
	from openai._utils import PropertyInfo, _transform, strip_annotated_type

	seen: set[int] = set()

	def walk(t: Any) -> bool:
		if id(t) in seen:
			return False
		seen.add(id(t))
		if any(isinstance(a, PropertyInfo) and (a.alias or a.format) for a in getattr(t, '__metadata__', ())):
			return True
		if any(walk(arg) for arg in typing.get_args(t)):
			return True
		t = strip_annotated_type(t)
		return typing_extensions.is_typeddict(t) and any(map(walk, _transform.get_type_hints(t, include_extras=True).values()))

	return any(map(walk, types))


def _json(value: Any) -> bool:
	if isinstance(value, dict):
		return all(isinstance(k, str) and _json(v) for k, v in value.items())
	if isinstance(value, list):
		return all(map(_json, value))
	return value is None or isinstance(value, str | int | float | bool)


def provider_preflight(model: Any) -> str | None:
	"""One free GET of the model on its provider (OpenAI, Anthropic, Google; official endpoints only): a rejected key
	or an unknown model fails here, before a cloud browser is created and billed. Returns the error line, or None when
	the model is there or it cannot be told (another endpoint, no API key at hand, the provider unreachable, or a key
	that may run the model without being allowed to look it up: 403, a 401 that is not an invalid key)."""
	system, name = getattr(model, 'system', None), getattr(model, 'model_name', None)
	try:
		client = model.client
		if system == 'openai' and urlparse(str(client.base_url)).hostname == 'api.openai.com':
			key = client.api_key
			url, headers = f'{str(client.base_url).rstrip("/")}/models/{name}', {'Authorization': f'Bearer {key}'}
		elif system == 'anthropic' and urlparse(str(client.base_url)).hostname == 'api.anthropic.com':
			key = client.api_key  # None for a client built with auth_token: nothing to check here
			url = f'{str(client.base_url).rstrip("/")}/v1/models/{name}'
			headers = {'x-api-key': str(key), 'anthropic-version': '2023-06-01'}
		elif system in ('google', 'google-gla') and not getattr(client._api_client, 'vertexai', False):
			api = client._api_client
			if urlparse(str(api._http_options.base_url)).hostname != GOOGLE_HOST:  # a proxy: its key is not Google's
				return None
			key, path = api.api_key, name if '/' in str(name) else f'models/{name}'  # 'models/gemini-2.5-flash' as is
			url, headers = f'https://{GOOGLE_HOST}/v1beta/{path}', {'x-goog-api-key': key}
		else:
			return None
		if not key or not isinstance(key, str):
			return None
	except Exception:  # - a Model without the client we know
		return None
	try:
		with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=PREFLIGHT_TIMEOUT_S):
			return None
	except urllib.error.HTTPError as e:
		try:
			error = json.loads(e.read()).get('error')
		except (ValueError, AttributeError):
			error = None
		error = error if isinstance(error, dict) else {'message': str(error or '')}
		detail = str(error.get('message') or '')[:300].replace(key, '<api key>')
		said = f': {detail.rstrip(".")}' if detail else ''
		reasons = {d.get('reason') for d in error.get('details') or () if isinstance(d, dict)}
		if (
			error.get('code') == 'invalid_api_key'  # OpenAI 401
			or error.get('type') == 'authentication_error'  # Anthropic 401
			or 'API_KEY_INVALID' in reasons  # Google answers a bad key with 400
			or (e.code == 401 and error.get('status') == 'UNAUTHENTICATED')
		):
			return f'{system} rejected the API key ({e.code}){said}. No browser was started.'
		if e.code == 404:
			return f'{name} is not a model this {system} key can use (404){said}. No browser was started.'
		return None
	except (OSError, ValueError):  # unreachable: the run itself will say
		return None


def gateway_llm(model: Any) -> ChatBrowserUse | None:
	"""The ChatBrowserUse behind a resolved gateway model (from ChatBrowserUse, ChatOpenAI(base_url=gateway), or their
	pydantic_model()), with the key that model sends; None for any other model."""
	llm = getattr(model, 'browser_use_llm', None)
	return llm if isinstance(llm, ChatBrowserUse) else None


def as_chat_model(llm: Any) -> Any:
	"""None and 'bu-*' strings -> ChatBrowserUse. Other supported models are returned unchanged; anything else (a
	LangChain chat model) raises here, in Agent(), not at run()."""
	from pydantic_ai.models import Model

	if llm is None:
		return ChatBrowserUse()
	if isinstance(llm, str) and llm.startswith('bu-'):
		return ChatBrowserUse(llm)
	if not isinstance(llm, (*CHAT_MODELS, Model, str)):
		raise _unsupported_llm(llm)
	return llm


def _unsupported_llm(llm: Any) -> TypeError:
	cls = f'{type(llm).__module__}.{type(llm).__qualname__}'  # langchain_openai.ChatOpenAI is not browser_use.ChatOpenAI
	return TypeError(
		f'llm={cls} is not supported in browser-use 1.0 (LangChain and other third-party chat models are not). Pass '
		'browser_use.ChatBrowserUse(), ChatOpenAI(...), ChatAnthropic(...), ChatGoogle(...), a Pydantic AI model string like '
		"'openai:gpt-4o' or a Pydantic AI Model. See MIGRATING.md."
	)


def resolve_model(llm: Any) -> tuple[Any, dict]:
	"""-> (Pydantic AI Model, extra model settings). Raises before any browser starts: missing key, missing extra."""
	from pydantic_ai.exceptions import UserError

	try:
		return _resolve_model(llm)
	except UserError as e:  # Pydantic AI's missing-key text names its provider classes and suggests Agent('test')
		if not (env := re.match(r'Set the `(\w+)` environment variable', str(e))):
			raise
		raise UserError(f'{env[1]} is not set: export it, put it in .env, or pass api_key=... to the model.') from None


def _resolve_model(llm: Any) -> tuple[Any, dict]:
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
	raise _unsupported_llm(llm)


def __getattr__(name: str):
	"""from browser_use.llm import ChatGroq (a 0.x import path): the removal message, not a bare ImportError."""
	from browser_use import _REMOVED

	if name.startswith('Chat') and name in _REMOVED:
		from browser_use.exceptions import removed

		raise ImportError(removed(f'browser_use.llm.{name}', _REMOVED[name]))
	raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


__all__ = ['ChatAnthropic', 'ChatBrowserUse', 'ChatGoogle', 'ChatOpenAI', 'GATEWAY_URL', 'model_ref', 'resolve_model']
