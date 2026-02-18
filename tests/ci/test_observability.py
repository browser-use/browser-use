"""Regression tests for optional lmnr observability integration."""

import builtins
import importlib
import sys


def _reload_observability_module():
	"""Import a fresh copy of browser_use.observability for import-time behavior checks."""
	sys.modules.pop('browser_use.observability', None)
	return importlib.import_module('browser_use.observability')


def test_observability_handles_broken_lmnr_import(monkeypatch):
	"""A broken lmnr install should gracefully fall back to no-op decorators."""
	original_import = builtins.__import__

	def _broken_lmnr_import(name, *args, **kwargs):
		if name == 'lmnr':
			raise TypeError('broken lmnr package')
		return original_import(name, *args, **kwargs)

	monkeypatch.setattr(builtins, '__import__', _broken_lmnr_import)

	observability = _reload_observability_module()
	assert observability.is_lmnr_available() is False

	@observability.observe(name='test_observe')
	def _wrapped() -> str:
		return 'ok'

	assert _wrapped() == 'ok'
