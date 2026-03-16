"""Tests for dynamic sensitive_data callable support (issue #2861)."""

from typing import Any, cast
from unittest.mock import MagicMock

from pydantic import BaseModel

from browser_use.tools.registry.service import Registry


class MockParams(BaseModel):
	text: str


class MockBrowserSession:
	pass


def _make_registry() -> Registry[object]:
	"""Create a minimal Registry for testing _replace_sensitive_data."""
	registry = Registry.__new__(Registry)
	object.__setattr__(registry, 'browser_session', MockBrowserSession())
	return registry


def test_static_string_values_still_work():
	"""Static string values should work unchanged."""
	registry = _make_registry()
	params = MockParams(text='<secret>password</secret>')
	result = cast(MockParams, registry._replace_sensitive_data(params, {'password': 'hunter2'}))
	assert result.text == 'hunter2'


def test_callable_values_are_resolved():
	"""Callable values should be called at replacement time."""
	registry = _make_registry()
	counter = {'n': 0}

	def get_totp() -> str:
		counter['n'] += 1
		return f'code-{counter["n"]}'

	params = MockParams(text='<secret>totp_code</secret>')
	result = cast(MockParams, registry._replace_sensitive_data(params, {'totp_code': get_totp}))
	assert result.text == 'code-1'

	# Call again - should get a fresh value
	params2 = MockParams(text='<secret>totp_code</secret>')
	result2 = cast(MockParams, registry._replace_sensitive_data(params2, {'totp_code': get_totp}))
	assert result2.text == 'code-2'


def test_domain_scoped_callable_values():
	"""Callable values inside domain-scoped dicts should be resolved."""
	registry = _make_registry()

	def get_token() -> str:
		return 'dynamic-token-123'

	sensitive: dict[str, Any] = {'https://example.com': {'api_key': get_token}}
	params = MockParams(text='<secret>api_key</secret>')
	result = cast(MockParams, registry._replace_sensitive_data(params, sensitive, current_url='https://example.com/page'))
	assert result.text == 'dynamic-token-123'


def test_callable_not_called_for_wrong_domain():
	"""Callable values should not be called when domain doesn't match."""
	spy = MagicMock(return_value='secret-value')
	sensitive: dict[str, Any] = {'https://other.com': {'api_key': spy}}
	registry = _make_registry()
	params = MockParams(text='<secret>api_key</secret>')
	registry._replace_sensitive_data(params, sensitive, current_url='https://example.com/page')
	spy.assert_not_called()


def test_mixed_static_and_callable():
	"""Mix of static strings and callables should both work."""
	registry = _make_registry()
	sensitive: dict[str, Any] = {
		'username': 'alice',
		'otp': lambda: '123456',
	}
	params = MockParams(text='<secret>username</secret> <secret>otp</secret>')
	result = cast(MockParams, registry._replace_sensitive_data(params, sensitive))
	assert result.text == 'alice 123456'


def test_literal_secret_callable_resolution():
	"""When LLM forgets tags and uses literal placeholder name, callables should still resolve."""
	registry = _make_registry()
	sensitive: dict[str, Any] = {'token': lambda: 'resolved-token'}
	params = MockParams(text='token')
	result = cast(MockParams, registry._replace_sensitive_data(params, sensitive))
	assert result.text == 'resolved-token'
