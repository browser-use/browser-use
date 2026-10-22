"""Regression tests for NVIDIA client setup."""

import pytest

from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.models import get_llm_by_name
from browser_use.llm.nvidia.chat import ChatNvidia


def test_provider_key_does_not_fall_back_to_openai_key(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('OPENAI_API_KEY', 'wrong-provider-key')
	monkeypatch.setenv('NVIDIA_API_KEY', 'nvidia-key')
	assert ChatNvidia(model='nvidia/nemotron-3.5-super-vl-120b-a12b')._client().api_key == 'nvidia-key'

	monkeypatch.delenv('NVIDIA_API_KEY')
	with pytest.raises(ModelProviderError, match='Missing NVIDIA API key') as exc_info:
		ChatNvidia(model='nvidia/nemotron-3.5-super-vl-120b-a12b')._client()
	assert exc_info.value.status_code == 401


def test_explicit_api_key_takes_precedence_over_env(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('NVIDIA_API_KEY', 'env-key')
	assert ChatNvidia(model='nvidia/nemotron-3.5-super-vl-120b-a12b', api_key='explicit-key')._client().api_key == 'explicit-key'


def test_default_model_and_base_url(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('NVIDIA_API_KEY', 'nvidia-key')
	llm = ChatNvidia()
	assert llm.provider == 'nvidia'
	assert llm.model == 'nvidia/nemotron-3.5-super-vl-120b-a12b'
	assert str(llm._client().base_url).rstrip('/') == 'https://integrate.api.nvidia.com/v1'


def test_base_url_is_overridable_for_self_hosted_nim(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('NVIDIA_API_KEY', 'nvidia-key')
	llm = ChatNvidia(base_url='http://localhost:8000/v1')
	assert str(llm._client().base_url).rstrip('/') == 'http://localhost:8000/v1'


def test_get_llm_by_name_resolves_nvidia_from_env(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('NVIDIA_API_KEY', 'nvidia-test-key')

	llm = get_llm_by_name('nvidia_nvidia/nemotron-3.5-super-vl-120b-a12b')

	assert isinstance(llm, ChatNvidia)
	assert llm.model == 'nvidia/nemotron-3.5-super-vl-120b-a12b'
	assert llm.api_key == 'nvidia-test-key'
