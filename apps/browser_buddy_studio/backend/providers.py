from __future__ import annotations

import logging
import subprocess

import keyring

from browser_use import ChatAnthropic, ChatBrowserUse, ChatDeepSeek, ChatGoogle, ChatOpenAI

KEYRING_SERVICE = 'BrowserBuddy'
DEEPSEEK_BASE_URL = 'https://api.deepseek.com'

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


def _keychain_has_item(service: str, account: str) -> bool:
	try:
		result = subprocess.run(
			['security', 'find-generic-password', '-s', service, '-a', account],
			capture_output=True,
			timeout=5,
		)
		return result.returncode == 0
	except Exception:
		return False


def get_saved_key(provider: str) -> str:
	if provider in _KEY_CACHE:
		return _KEY_CACHE[provider]
	try:
		key = keyring.get_password(KEYRING_SERVICE, PROVIDERS[provider]['key_name']) or ''
		if key:
			_KEY_CACHE[provider] = key
		return key
	except Exception as e:
		logger.warning(f'Could not read API key for {provider}: {type(e).__name__}: {e}')
		return ''


def save_key(provider: str, api_key: str) -> None:
	if _KEY_CACHE.get(provider) == api_key:
		return
	try:
		keyring.set_password(KEYRING_SERVICE, PROVIDERS[provider]['key_name'], api_key)
		_KEY_CACHE[provider] = api_key
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
	result = []
	for name, config in PROVIDERS.items():
		result.append(
			{
				'name': name,
				'default_model': config['default_model'],
				'placeholder': config['placeholder'],
				'has_key': name in _KEY_CACHE or _keychain_has_item(KEYRING_SERVICE, config['key_name']),
			}
		)
	return result
