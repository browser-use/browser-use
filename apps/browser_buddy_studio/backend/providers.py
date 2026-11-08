from __future__ import annotations

import json
import logging
import os
import threading

from browser_use import ChatAnthropic, ChatBrowserUse, ChatDeepSeek, ChatGoogle, ChatOpenAI

from .config import APP_SUPPORT_DIR

DEEPSEEK_BASE_URL = 'https://api.deepseek.com'
SECRETS_FILE = APP_SUPPORT_DIR / 'secrets.json'

PROVIDERS = {
	'DeepSeek': {
		'key_name': 'deepseek-api-key',
		'default_model': 'deepseek-v4-flash',
		'placeholder': 'sk-...',
	},
	'Browser Use': {
		'key_name': 'browser-use-api-key',
		'default_model': 'bu-2-0-mini-preview',
		'placeholder': 'bu-...',
	},
	'OpenAI': {
		'key_name': 'openai-api-key',
		'default_model': 'gpt-4.1-mini',
		'placeholder': 'sk-...',
	},
	'Anthropic': {
		'key_name': 'anthropic-api-key',
		'default_model': 'claude-sonnet-4-0',
		'placeholder': 'sk-ant-...',
	},
	'Google Gemini': {
		'key_name': 'google-api-key',
		'default_model': 'gemini-3-flash-preview',
		'placeholder': 'AIza...',
	},
}

logger = logging.getLogger('browser_buddy.providers')
_KEY_CACHE: dict[str, str] = {}
_SECRETS_LOCK = threading.Lock()


def _load_secrets() -> dict[str, str]:
	try:
		data = json.loads(SECRETS_FILE.read_text(encoding='utf-8'))
	except Exception:
		return {}
	if not isinstance(data, dict):
		return {}
	return {str(key): str(value) for key, value in data.items() if isinstance(value, str) and value}


def _write_secrets(data: dict[str, str]) -> None:
	SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
	temp = SECRETS_FILE.with_suffix(SECRETS_FILE.suffix + '.tmp')
	temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
	try:
		os.chmod(temp, 0o600)
	except Exception:
		pass
	temp.replace(SECRETS_FILE)
	try:
		os.chmod(SECRETS_FILE, 0o600)
	except Exception:
		pass


def get_saved_key(provider: str) -> str:
	if provider in _KEY_CACHE:
		return _KEY_CACHE[provider]
	try:
		key_name = PROVIDERS[provider]['key_name']
		with _SECRETS_LOCK:
			key = _load_secrets().get(key_name, '')
		if key:
			_KEY_CACHE[provider] = key
		return key
	except Exception as e:
		logger.warning(f'Could not read API key for {provider}: {type(e).__name__}: {e}')
		return ''


def save_key(provider: str, api_key: str) -> None:
	api_key = (api_key or '').strip()
	if _KEY_CACHE.get(provider) == api_key:
		return
	try:
		key_name = PROVIDERS[provider]['key_name']
		with _SECRETS_LOCK:
			data = _load_secrets()
			if api_key:
				data[key_name] = api_key
			else:
				data.pop(key_name, None)
			_write_secrets(data)
		if api_key:
			_KEY_CACHE[provider] = api_key
		else:
			_KEY_CACHE.pop(provider, None)
	except Exception as e:
		logger.warning(f'Could not save API key for {provider}: {type(e).__name__}: {e}')


def build_llm(provider: str, model: str, api_key: str):
	if provider == 'DeepSeek':
		return ChatDeepSeek(model=model, api_key=api_key, base_url=DEEPSEEK_BASE_URL)
	if provider == 'Browser Use':
		return ChatBrowserUse(model=model, api_key=api_key)
	if provider == 'OpenAI':
		return ChatOpenAI(model=model, api_key=api_key)
	if provider == 'Anthropic':
		return ChatAnthropic(model=model, api_key=api_key)
	if provider == 'Google Gemini':
		return ChatGoogle(model=model, api_key=api_key)
	raise ValueError(f'Unsupported provider: {provider}')


def provider_list() -> list[dict]:
	with _SECRETS_LOCK:
		saved_keys = _load_secrets()
	result = []
	for name, config in PROVIDERS.items():
		result.append(
			{
				'name': name,
				'default_model': config['default_model'],
				'placeholder': config['placeholder'],
				'has_key': name in _KEY_CACHE or bool(saved_keys.get(config['key_name'])),
			}
		)
	return result
