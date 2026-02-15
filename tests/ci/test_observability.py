"""Tests for observability module's lmnr import error handling.

Regression tests for https://github.com/browser-use/browser-use/issues/4046
"""

import importlib
import sys
from unittest.mock import MagicMock, patch


class TestLmnrImportFallback:
	"""Test that observability gracefully handles lmnr import failures."""

	def _reload_observability(self):
		"""Reload the observability module to re-trigger import logic."""
		if 'browser_use.observability' in sys.modules:
			del sys.modules['browser_use.observability']
		import browser_use.observability

		return browser_use.observability

	def test_fallback_when_lmnr_not_installed(self):
		"""Test that observability works when lmnr is not installed (ImportError)."""
		original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

		def mock_import(name, *args, **kwargs):
			if name == 'lmnr':
				raise ImportError('No module named lmnr')
			return original_import(name, *args, **kwargs)

		with patch('builtins.__import__', side_effect=mock_import):
			mod = self._reload_observability()

		assert mod._LMNR_AVAILABLE is False
		assert mod._lmnr_observe is None

		# observe should return a working no-op decorator
		decorator = mod.observe(name='test')
		assert callable(decorator)

	def test_fallback_when_lmnr_raises_type_error(self):
		"""Test that observability works when lmnr raises TypeError on import.

		Regression test for #4046: On some setups (e.g., Python 3.13 with certain
		package states), lmnr is installed but internally raises TypeError instead
		of ImportError, crashing the entire application on startup.
		"""
		original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

		def mock_import(name, *args, **kwargs):
			if name == 'lmnr':
				raise TypeError('unsupported callable')
			return original_import(name, *args, **kwargs)

		with patch('builtins.__import__', side_effect=mock_import):
			mod = self._reload_observability()

		assert mod._LMNR_AVAILABLE is False
		assert mod._lmnr_observe is None

		# observe should return a working no-op decorator
		decorator = mod.observe(name='test')
		assert callable(decorator)

	def test_observe_noop_decorator_works_on_sync_function(self):
		"""Test that the no-op decorator correctly wraps sync functions."""
		original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

		def mock_import(name, *args, **kwargs):
			if name == 'lmnr':
				raise ImportError('No module named lmnr')
			return original_import(name, *args, **kwargs)

		with patch('builtins.__import__', side_effect=mock_import):
			mod = self._reload_observability()

		@mod.observe(name='test_func')
		def my_func(x, y):
			return x + y

		assert my_func(1, 2) == 3

	def test_observe_noop_decorator_works_on_async_function(self):
		"""Test that the no-op decorator correctly wraps async functions."""
		import asyncio

		original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

		def mock_import(name, *args, **kwargs):
			if name == 'lmnr':
				raise ImportError('No module named lmnr')
			return original_import(name, *args, **kwargs)

		with patch('builtins.__import__', side_effect=mock_import):
			mod = self._reload_observability()

		@mod.observe(name='test_async_func')
		async def my_async_func(x, y):
			return x + y

		result = asyncio.run(my_async_func(3, 4))
		assert result == 7
