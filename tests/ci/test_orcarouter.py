import asyncio
import base64
import hashlib
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from werkzeug.wrappers import Request, Response

from browser_use.config import load_and_migrate_config
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import ContentPartTextParam, SystemMessage, UserMessage
from browser_use.llm.orcarouter.auth import (
	OrcaRouterAuthError,
	OrcaRouterCredentialStore,
	OrcaRouterPKCEClient,
)
from browser_use.llm.orcarouter.chat import ChatOrcaRouter
from browser_use.llm.orcarouter.serializer import OrcaRouterMessageSerializer
from browser_use.llm.views import ChatInvokeUsage
from browser_use.tokens.service import TokenCost


def test_orcarouter_serializer_uses_openai_format() -> None:
	"""OrcaRouter speaks the OpenAI wire format, so the serializer must match OpenAI's."""
	messages = [
		SystemMessage(content=[ContentPartTextParam(text='You are a helpful assistant.', type='text')]),
		UserMessage(content='What is the capital of France? Answer in one word.'),
	]

	serialized = OrcaRouterMessageSerializer.serialize_messages(messages)

	assert serialized == [
		{'role': 'system', 'content': [{'type': 'text', 'text': 'You are a helpful assistant.'}]},
		{'role': 'user', 'content': 'What is the capital of France? Answer in one word.'},
	]


def test_orcarouter_chat_defaults() -> None:
	"""ChatOrcaRouter must expose the OrcaRouter provider and default gateway base URL."""
	chat = ChatOrcaRouter(model='orcarouter/auto', api_key='test-key')

	assert chat.provider == 'orcarouter'
	assert str(chat.base_url) == 'https://api.orcarouter.ai/v1'
	assert chat.name == 'orcarouter/auto'


async def test_registered_orcarouter_llm_never_matches_upstream_pricing(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""OrcaRouter is a gateway; upstream model pricing must not be attributed to it."""
	seen_model_names = []

	async def fake_openrouter_pricing(model_name: str):
		seen_model_names.append(model_name)
		return None

	monkeypatch.setattr('browser_use.tokens.service.get_openrouter_model_pricing', fake_openrouter_pricing)

	token_cost = TokenCost(include_cost=True)
	token_cost._initialized = True
	token_cost._pricing_data = {}
	token_cost.register_llm(ChatOrcaRouter(model='openai/gpt-4o-mini', api_key='test-key'))

	cost = await token_cost.calculate_cost(
		'openai/gpt-4o-mini',
		ChatInvokeUsage(
			prompt_tokens=10,
			prompt_cached_tokens=None,
			prompt_cache_creation_tokens=None,
			prompt_image_tokens=None,
			completion_tokens=5,
			total_tokens=15,
		),
	)

	assert seen_model_names == ['orcarouter/openai/gpt-4o-mini']
	assert cost is None


def test_orcarouter_reads_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
	"""ORCAROUTER_API_KEY is the documented env var, so it must actually be read."""
	monkeypatch.setenv('ORCAROUTER_API_KEY', 'orca-key')
	monkeypatch.setenv('OPENAI_API_KEY', 'sk-unrelated-openai-key')

	client = ChatOrcaRouter(model='orcarouter/auto').get_client()

	assert client.api_key == 'orca-key'


def test_orcarouter_never_falls_back_to_the_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
	"""An unset OrcaRouter key must fail loudly, not ship OPENAI_API_KEY to the gateway."""
	monkeypatch.delenv('ORCAROUTER_API_KEY', raising=False)
	monkeypatch.setenv('OPENAI_API_KEY', 'sk-unrelated-openai-key')

	with pytest.raises(ModelProviderError) as exc_info:
		ChatOrcaRouter(model='orcarouter/auto').get_client()

	assert exc_info.value.status_code == 401
	assert 'sk-unrelated-openai-key' not in str(exc_info.value)


def _fake_orcarouter_key(character: str = 'a') -> str:
	return 'sk-orca-' + (character * 48)


async def test_pkce_login_uses_s256_loopback_callback_and_persists_api_scope(httpserver, tmp_path: Path) -> None:
	exchange_request: dict[str, str] = {}
	issued_key = _fake_orcarouter_key()

	def exchange(request: Request) -> Response:
		exchange_request.update(request.get_json())
		return Response(
			response=f'{{"key":"{issued_key}","user_id":"user-123","scope":"api"}}',
			status=200,
			content_type='application/json',
		)

	httpserver.expect_request('/api/v1/auth/keys', method='POST').respond_with_handler(exchange)
	store = OrcaRouterCredentialStore(tmp_path / 'config.json')
	client = OrcaRouterPKCEClient(auth_base_url=httpserver.url_for(''), credential_store=store)
	authorization_url: str | None = None

	def authorize(url: str) -> None:
		nonlocal authorization_url
		authorization_url = url

		async def send_callback() -> None:
			query = parse_qs(urlparse(url).query)
			callback_url = query['callback_url'][0]
			async with httpx.AsyncClient() as callback_client:
				await callback_client.get(callback_url, params={'code': 'one-time-code', 'state': query['state'][0]})

		asyncio.create_task(send_callback())

	credential = await client.login(open_browser=False, on_authorization_url=authorize, timeout=2)

	assert authorization_url is not None
	parsed_url = urlparse(authorization_url)
	query = parse_qs(parsed_url.query)
	assert parsed_url.path == '/auth'
	assert query['code_challenge_method'] == ['S256']
	assert query['scope'] == ['api']
	assert query['app_name'] == ['Browser Use']
	assert 'client_id' not in query
	assert 'appid' not in query
	assert 'code_verifier' not in query
	assert query['callback_url'][0].startswith('http://127.0.0.1:')
	assert exchange_request['code'] == 'one-time-code'
	assert exchange_request['code_challenge_method'] == 'S256'
	expected_challenge = (
		base64.urlsafe_b64encode(hashlib.sha256(exchange_request['code_verifier'].encode()).digest()).rstrip(b'=').decode()
	)
	assert query['code_challenge'] == [expected_challenge]
	assert exchange_request['code_verifier'] not in authorization_url
	assert issued_key not in authorization_url
	assert credential.scope == 'api'
	assert credential.api_key == issued_key
	assert store.load() == credential
	assert os.stat(store.path).st_mode & 0o777 == 0o600


async def test_pkce_state_mismatch_is_rejected_before_exchange(httpserver, tmp_path: Path) -> None:
	httpserver.expect_request('/api/v1/auth/keys', method='POST').respond_with_json(
		{'key': _fake_orcarouter_key(), 'user_id': 'user-123', 'scope': 'api'}
	)
	store = OrcaRouterCredentialStore(tmp_path / 'config.json')
	client = OrcaRouterPKCEClient(auth_base_url=httpserver.url_for(''), credential_store=store)
	mismatch_status: int | None = None

	def authorize(url: str) -> None:
		async def send_callbacks() -> None:
			nonlocal mismatch_status
			query = parse_qs(urlparse(url).query)
			callback_url = query['callback_url'][0]
			async with httpx.AsyncClient() as callback_client:
				mismatch = await callback_client.get(callback_url, params={'code': 'attacker-code', 'state': 'wrong-state'})
				mismatch_status = mismatch.status_code
				await callback_client.get(callback_url, params={'code': 'real-code', 'state': query['state'][0]})

		asyncio.create_task(send_callbacks())

	credential = await client.login(open_browser=False, on_authorization_url=authorize, timeout=2)

	assert mismatch_status == 400
	assert credential.api_key == _fake_orcarouter_key()


async def test_pkce_rejects_downgraded_scope_and_does_not_persist(httpserver, tmp_path: Path) -> None:
	httpserver.expect_request('/api/v1/auth/keys', method='POST').respond_with_json(
		{'key': _fake_orcarouter_key(), 'user_id': 'user-123', 'scope': 'profile'}
	)
	store = OrcaRouterCredentialStore(tmp_path / 'config.json')
	client = OrcaRouterPKCEClient(auth_base_url=httpserver.url_for(''), credential_store=store)

	def authorize(url: str) -> None:
		async def send_callback() -> None:
			query = parse_qs(urlparse(url).query)
			async with httpx.AsyncClient() as callback_client:
				await callback_client.get(
					query['callback_url'][0],
					params={'code': 'one-time-code', 'state': query['state'][0]},
				)

		asyncio.create_task(send_callback())

	with pytest.raises(OrcaRouterAuthError, match='scope'):
		await client.login(open_browser=False, on_authorization_url=authorize, timeout=2)

	assert store.load() is None


def test_orcarouter_key_priority_is_explicit_then_env_then_pkce(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
	stored_key = _fake_orcarouter_key('s')
	env_key = _fake_orcarouter_key('e')
	explicit_key = _fake_orcarouter_key('x')
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))
	OrcaRouterCredentialStore().save(key=stored_key, user_id='user-123')

	monkeypatch.setenv('ORCAROUTER_API_KEY', env_key)
	assert ChatOrcaRouter(model='orcarouter/auto', api_key=explicit_key).get_client().api_key == explicit_key
	assert ChatOrcaRouter(model='orcarouter/auto').get_client().api_key == env_key

	monkeypatch.delenv('ORCAROUTER_API_KEY')
	assert ChatOrcaRouter(model='orcarouter/auto').get_client().api_key == stored_key


def test_needs_reauth_key_is_preserved_but_not_reused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))
	store = OrcaRouterCredentialStore()
	credential = store.save(key=_fake_orcarouter_key(), user_id='user-123')
	assert store.mark_needs_reauth(credential.generation)

	with pytest.raises(ModelProviderError, match='orcarouter login') as exc_info:
		ChatOrcaRouter(model='orcarouter/auto').get_client()

	assert exc_info.value.status_code == 401
	loaded = store.load()
	assert loaded is not None
	assert loaded.api_key == credential.api_key


async def test_stored_pkce_key_401_is_marked_needs_reauth(httpserver, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))
	monkeypatch.delenv('ORCAROUTER_API_KEY', raising=False)
	store = OrcaRouterCredentialStore()
	credential = store.save(key=_fake_orcarouter_key(), user_id='user-123')
	httpserver.expect_request('/v1/chat/completions', method='POST').respond_with_json(
		{'error': {'message': 'invalid api key', 'type': 'authentication_error'}}, status=401
	)
	chat = ChatOrcaRouter(
		model='orcarouter/auto',
		base_url=httpserver.url_for('/v1'),
		max_retries=0,
	)

	with pytest.raises(ModelProviderError) as exc_info:
		await chat.ainvoke([UserMessage(content='hello')])

	assert exc_info.value.status_code == 401
	loaded = store.load()
	assert loaded is not None
	assert loaded.generation == credential.generation
	assert loaded.needs_reauth is True
	assert loaded.api_key == credential.api_key
	with pytest.raises(ModelProviderError, match='orcarouter login'):
		await chat.ainvoke([UserMessage(content='do not retry with the rejected key')])


def test_stale_401_cannot_invalidate_a_replacement_key(tmp_path: Path) -> None:
	store = OrcaRouterCredentialStore(tmp_path / 'config.json')
	old = store.save(key=_fake_orcarouter_key('o'), user_id='user-old')
	new = store.save(key=_fake_orcarouter_key('n'), user_id='user-new')

	assert store.mark_needs_reauth(old.generation) is False
	assert store.load() == new


async def test_pkce_attempts_use_fresh_secrets_and_close_listener_on_timeout(tmp_path: Path) -> None:
	store = OrcaRouterCredentialStore(tmp_path / 'config.json')
	client = OrcaRouterPKCEClient(auth_base_url='http://127.0.0.1:9', credential_store=store)
	authorization_urls: list[str] = []

	for _ in range(2):
		with pytest.raises(OrcaRouterAuthError, match='Timed out'):
			await client.login(
				open_browser=False,
				on_authorization_url=authorization_urls.append,
				timeout=0.01,
			)

	first = parse_qs(urlparse(authorization_urls[0]).query)
	second = parse_qs(urlparse(authorization_urls[1]).query)
	assert first['state'] != second['state']
	assert first['code_challenge'] != second['code_challenge']

	async with httpx.AsyncClient() as callback_client:
		with pytest.raises(httpx.ConnectError):
			await callback_client.get(first['callback_url'][0])


def test_split_origins_override_shared_self_hosted_origin(monkeypatch: pytest.MonkeyPatch) -> None:
	for name in (
		'ORCAROUTER_AUTH_BASE_URL',
		'ORCAROUTER_API_BASE_URL',
		'ORCAROUTER_BASE_URL',
		'ORCA_AUTH_BASE_URL',
		'ORCA_API_BASE_URL',
		'ORCA_BASE_URL',
	):
		monkeypatch.delenv(name, raising=False)
	monkeypatch.setenv('ORCA_BASE_URL', 'https://shared.example')
	assert OrcaRouterPKCEClient().auth_base_url == 'https://shared.example'
	assert str(ChatOrcaRouter(model='orcarouter/auto', api_key='test-key').base_url) == 'https://shared.example/v1'

	monkeypatch.setenv('ORCA_AUTH_BASE_URL', 'https://auth.example')
	monkeypatch.setenv('ORCA_API_BASE_URL', 'https://api.example/custom/v1')
	assert OrcaRouterPKCEClient().auth_base_url == 'https://auth.example'
	assert str(ChatOrcaRouter(model='orcarouter/auto', api_key='test-key').base_url) == 'https://api.example/custom/v1'


def test_remote_auth_origin_requires_https() -> None:
	with pytest.raises(OrcaRouterAuthError, match='HTTPS'):
		OrcaRouterPKCEClient(auth_base_url='http://auth.example')
	with pytest.raises(OrcaRouterAuthError, match='HTTPS'):
		ChatOrcaRouter(model='orcarouter/auto', api_key='test-key', base_url='http://api.example/v1').get_client()


def test_pkce_credential_uses_native_config_without_breaking_config_loading(tmp_path: Path) -> None:
	store = OrcaRouterCredentialStore(tmp_path / 'config.json')
	credential = store.save(key=_fake_orcarouter_key(), user_id='user-123')

	config = load_and_migrate_config(store.path)
	entry = next(item for item in config.llm.values() if item.provider == 'orcarouter')
	assert entry.api_key == credential.api_key
	assert entry.auth_method == 'pkce'
	assert store.load() == credential
