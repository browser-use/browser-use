"""Regression tests for recursive sensitive data filtering."""

from copy import deepcopy

import pytest

from browser_use.utils import filter_sensitive_data


@pytest.mark.parametrize('sensitive_data', [{'value': 'super-secret'}, {'example.com': {'value': 'super-secret'}}])
def test_filter_sensitive_data_redacts_dictionary_keys(sensitive_data):
	"""Keys and values are redacted throughout containers without modifying the input."""
	data = {
		'super-secret.md': 'super-secret',
		'ordinary': [{'nested-super-secret': ('super-secret', {'super-secret': 'safe'})}],
		42: {'super-secret': None},
		('super-secret',): False,
	}
	original = deepcopy(data)

	assert filter_sensitive_data(data, sensitive_data) == {
		'<secret>value</secret>.md': '<secret>value</secret>',
		'ordinary': [{'nested-<secret>value</secret>': ('<secret>value</secret>', {'<secret>value</secret>': 'safe'})}],
		42: {'<secret>value</secret>': None},
		('super-secret',): False,
	}
	assert data == original


@pytest.mark.parametrize('sensitive_data', [None, {}, {'value': ''}, {'example.com': {'value': ''}}])
def test_filter_sensitive_data_without_secrets_preserves_input(sensitive_data):
	"""Empty sensitive data retains the existing no-copy fast path."""
	data = {'ordinary': [{'nested': 'safe'}]}
	assert filter_sensitive_data(data, sensitive_data) is data
