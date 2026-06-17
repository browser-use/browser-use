"""Regression tests for the search_page ReDoS hardening.

The ``search_page`` browser action compiles a model-controlled pattern with
``new RegExp(PATTERN, flags)`` inside the page's V8 engine and runs it over the
concatenated page text. V8's RegExp engine is backtracking-based, so a
"nested quantifier" pattern such as ``(a+)+$`` against long near-miss text can
exhibit catastrophic (exponential) runtime and tie up the browser action.

These tests pin the Python-side guard that rejects such patterns *before* they
ever reach ``new RegExp(...)``. They are hermetic (no browser, no network) and
the one test that actually exercises a backtracking engine is bounded by
construction (tiny input lengths) so it can never hang the suite.

The behavioural sink-level test (``test_build_rejects_poc_pattern``) depends only
on ``_build_search_page_js``, which already exists upstream, so it *runs* against
the unpatched code and fails there (the pattern is happily embedded into the
generated JS), and passes once the guard is added.
"""

import re
import time

import pytest

# _build_search_page_js exists in both the unpatched and patched trees, so this
# import succeeds either way and lets the behavioural test execute on both.
from browser_use.tools.service import _build_search_page_js

# Catastrophic-backtracking "evil regex" shapes that must be rejected in regex mode.
EVIL_PATTERNS = [
	'(a+)+$',  # the PoC pattern
	'(a*)*',
	'(a+)*',
	'(a*)+',
	'(ab+)+',
	'(?:a+)+',
	'((a)+)+',  # arbitrary nesting
	'(([a-z]+)*)+',
	r'(\d+)+$',
	'(a{2,})+',
	'(a+){3,}',
	'(.*)+',
]

# Legitimate patterns a model might reasonably emit; these must keep working.
SAFE_PATTERNS = [
	r'\d+\.\d+',
	r'\$\d+\.\d{2}',
	'support@example.com',
	'a+',
	'[a-z]+',
	'(foo|bar)',
	'(abc)+',
	'(ab)+',
	'a{2,5}',
	r'[+*]+',  # quantifier chars only inside a character class — not nested
	r'\(a+\)+',  # escaped parens are literal, not a group
	'Widget A',
]


def _guard_helpers():
	"""Import the guard helpers lazily so helper-specific tests skip cleanly on
	an unpatched tree instead of erroring at collection time."""
	try:
		from browser_use.tools.service import (
			_MAX_SEARCH_PATTERN_LENGTH,
			_has_nested_quantifier,
			_validate_search_pattern,
		)
	except ImportError:
		pytest.skip('search_page ReDoS guard not present in this build')
	return _validate_search_pattern, _has_nested_quantifier, _MAX_SEARCH_PATTERN_LENGTH


class TestNestedQuantifierDetection:
	"""Unit coverage for the nested-quantifier detector."""

	@pytest.mark.parametrize('pattern', EVIL_PATTERNS)
	def test_evil_patterns_flagged(self, pattern):
		_, has_nested_quantifier, _ = _guard_helpers()
		assert has_nested_quantifier(pattern) is True, f'expected {pattern!r} to be flagged'

	@pytest.mark.parametrize('pattern', SAFE_PATTERNS)
	def test_safe_patterns_not_flagged(self, pattern):
		_, has_nested_quantifier, _ = _guard_helpers()
		assert has_nested_quantifier(pattern) is False, f'{pattern!r} should not be flagged'


class TestValidateSearchPattern:
	"""The validator should raise on unsafe input and accept safe input."""

	@pytest.mark.parametrize('pattern', EVIL_PATTERNS)
	def test_evil_regex_rejected(self, pattern):
		validate_search_pattern, _, _ = _guard_helpers()
		with pytest.raises(ValueError):
			validate_search_pattern(pattern, regex=True)

	@pytest.mark.parametrize('pattern', SAFE_PATTERNS)
	def test_safe_regex_accepted(self, pattern):
		validate_search_pattern, _, _ = _guard_helpers()
		validate_search_pattern(pattern, regex=True)  # should not raise

	def test_literal_mode_ignores_nested_quantifier(self):
		# In literal mode the pattern is escaped before compilation, so it cannot
		# backtrack pathologically; the nested-quantifier rule must not fire.
		validate_search_pattern, _, _ = _guard_helpers()
		validate_search_pattern('(a+)+$', regex=False)

	def test_pattern_length_cap(self):
		validate_search_pattern, _, max_len = _guard_helpers()
		too_long = 'a' * (max_len + 1)
		with pytest.raises(ValueError):
			validate_search_pattern(too_long, regex=False)
		with pytest.raises(ValueError):
			validate_search_pattern(too_long, regex=True)
		# Exactly at the cap is allowed.
		validate_search_pattern('a' * max_len, regex=False)


class TestBuildSearchPageJsGuard:
	"""The guard is enforced at the single chokepoint that feeds new RegExp(...).

	These tests use only ``_build_search_page_js`` so they execute on both the
	patched and unpatched trees — and fail on the unpatched tree.
	"""

	def test_build_rejects_poc_pattern(self):
		# Unpatched: returns a JS string embedding the evil pattern (no raise) -> FAILS here.
		# Patched: raises ValueError before any JS is built.
		with pytest.raises(ValueError):
			_build_search_page_js(
				pattern='(a+)+$',
				regex=True,
				case_sensitive=True,
				context_chars=150,
				css_scope=None,
				max_results=1,
			)

	def test_build_rejects_overlong_pattern(self):
		with pytest.raises(ValueError):
			_build_search_page_js(
				pattern='a' * 5000,
				regex=False,
				case_sensitive=False,
				context_chars=150,
				css_scope=None,
				max_results=25,
			)

	def test_build_allows_benign_regex(self):
		js = _build_search_page_js(
			pattern=r'\d+\.\d+',
			regex=True,
			case_sensitive=False,
			context_chars=150,
			css_scope=None,
			max_results=25,
		)
		assert 'var PATTERN' in js
		assert 'var IS_REGEX' in js  # template still intact


def _match_time(pattern: str, subject: str) -> float:
	"""Wall-clock seconds to attempt ``pattern`` against ``subject`` once."""
	compiled = re.compile(pattern)
	start = time.perf_counter()
	compiled.search(subject)
	return time.perf_counter() - start


class TestEvilPatternActuallyBacktracks:
	"""Demonstrate the threat is real, bounded by construction so it cannot hang.

	We use small input lengths where the PoC pattern ``(a+)+$`` already exhibits
	clear exponential growth in a backtracking engine (CPython ``re`` here stands
	in for the browser's V8 RegExp engine — both backtrack). The largest match
	attempted is ``n == 24`` (well under a second), keeping total runtime tiny.
	"""

	def test_poc_pattern_growth_is_super_linear(self):
		# Near-miss subjects for /(a+)+$/: a run of 'a' that fails the final anchor.
		# Each +2 in n should multiply the runtime, which a linear engine never would.
		t_small = _match_time('(a+)+$', 'a' * 20 + '!')
		t_large = _match_time('(a+)+$', 'a' * 24 + '!')

		# A safe linear pattern over the same (larger) input is effectively free.
		t_safe = _match_time('a+$', 'a' * 24 + '!')

		# Generous thresholds: robust across machines while still proving the pathology.
		assert t_large > t_small * 3, f'expected super-linear growth, got {t_small=} {t_large=}'
		assert t_large > t_safe * 20, f'expected evil >> safe, got {t_large=} {t_safe=}'

	def test_guard_blocks_the_catastrophic_pattern(self):
		# The guard rejects exactly this pattern before it can ever be compiled into
		# the page's RegExp engine, so the blow-up above can never actually run.
		validate_search_pattern, _, _ = _guard_helpers()
		with pytest.raises(ValueError):
			validate_search_pattern('(a+)+$', regex=True)
