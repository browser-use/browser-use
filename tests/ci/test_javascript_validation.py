from browser_use.tools.service import Tools


class TestJavaScriptValidation:
	"""Test the JavaScript validation and fixing function."""

	def test_original_bug_case(self):
		"""Test the exact case reported in the bug."""
		tools = Tools()
		original = (
			'(function() { '
			'var el = document.querySelector("div[role=\'button\'][pressed]"); '
			'if(el) el.focus(); '
			"return el ? el.getAttribute('aria-pressed') : 'not found'; "
			'})()'
		)
		fixed = tools._validate_and_fix_javascript(original)

		# Should not add extra parentheses
		assert fixed.count(')') == original.count(')'), (
			f'Parenthesis count mismatch. Original: {original.count(")")}, Fixed: {fixed.count(")")}'
		)
		# Should convert to template literal
		assert "`div[role='button'][pressed]`" in fixed or "`div[role='button'][pressed]`" in fixed
		# Should be valid JavaScript (no syntax errors)
		assert fixed.count('(') == fixed.count(')'), f'Unbalanced parentheses in: {fixed}'

	def test_querySelector_simple_mixed_quotes(self):
		"""Test querySelector with simple mixed quotes."""
		tools = Tools()
		code = 'document.querySelector("div[role=\'button\']")'
		fixed = tools._validate_and_fix_javascript(code)
		assert "`div[role='button']`" in fixed
		assert fixed.count('(') == fixed.count(')')
		assert "document.querySelector(`div[role='button']`)" in fixed

	def test_querySelectorAll_mixed_quotes(self):
		"""Test querySelectorAll with mixed quotes."""
		tools = Tools()
		code = 'document.querySelectorAll("div[class=\'test\'][id="foo"]")'
		fixed = tools._validate_and_fix_javascript(code)
		assert 'querySelectorAll' in fixed
		assert fixed.count('(') == fixed.count(')')

	def test_querySelector_multiple_attributes(self):
		"""Test querySelector with multiple attributes."""
		tools = Tools()
		code = 'document.querySelector("div[role=\'button\'][pressed]")'
		fixed = tools._validate_and_fix_javascript(code)
		assert "`div[role='button'][pressed]`" in fixed
		assert fixed.count('(') == fixed.count(')')
		# Should not have extra closing parens
		assert not fixed.endswith('))')

	def test_querySelector_no_mixed_quotes(self):
		"""Test querySelector without mixed quotes should not change."""
		tools = Tools()
		code = 'document.querySelector("div.button")'
		fixed = tools._validate_and_fix_javascript(code)
		# Should not change if no mixed quotes
		assert code == fixed or '`' not in fixed

	def test_querySelector_single_quotes_only(self):
		"""Test querySelector with only single quotes should not change."""
		tools = Tools()
		code = "document.querySelector('div.button')"
		fixed = tools._validate_and_fix_javascript(code)
		# Should not change
		assert code == fixed

	def test_closest_mixed_quotes(self):
		"""Test .closest() with mixed quotes."""
		tools = Tools()
		code = 'el.closest("div[role=\'button\']")'
		fixed = tools._validate_and_fix_javascript(code)
		assert ".closest(`div[role='button']`)" in fixed
		assert fixed.count('(') == fixed.count(')')

	def test_matches_mixed_quotes(self):
		"""Test .matches() with mixed quotes."""
		tools = Tools()
		code = 'el.matches("div[class=\'test\']")'
		fixed = tools._validate_and_fix_javascript(code)
		assert ".matches(`div[class='test']`)" in fixed
		assert fixed.count('(') == fixed.count(')')

	def test_document_evaluate_mixed_quotes(self):
		"""Test document.evaluate with mixed quotes."""
		tools = Tools()
		code = 'document.evaluate("//div[@role=\'button\']", document)'
		fixed = tools._validate_and_fix_javascript(code)
		assert "document.evaluate(`//div[@role='button']`," in fixed
		assert fixed.count('(') == fixed.count(')')

	def test_nested_function_calls(self):
		"""Test nested function calls with mixed quotes."""
		tools = Tools()
		code = 'var x = document.querySelector("div[role=\'button\']").getAttribute("data-value");'
		fixed = tools._validate_and_fix_javascript(code)
		assert fixed.count('(') == fixed.count(')')
		assert "querySelector(`div[role='button']`)" in fixed

	def test_multiple_querySelectors(self):
		"""Test multiple querySelector calls in one expression."""
		tools = Tools()
		code = 'var a = document.querySelector("div[role=\'a\']"); var b = document.querySelector("div[role=\'b\']");'
		fixed = tools._validate_and_fix_javascript(code)
		assert fixed.count('(') == fixed.count(')')
		assert fixed.count('querySelector') == 2

	def test_querySelector_in_function(self):
		"""Test querySelector inside a function."""
		tools = Tools()
		code = 'function test() { return document.querySelector("div[role=\'button\']"); }'
		fixed = tools._validate_and_fix_javascript(code)
		assert fixed.count('(') == fixed.count(')')
		assert "querySelector(`div[role='button']`)" in fixed

	def test_complex_selector_with_spaces(self):
		"""Test complex selector with spaces."""
		tools = Tools()
		code = "document.querySelector(\"div[role='button'][aria-label='Click me']\")"
		fixed = tools._validate_and_fix_javascript(code)
		assert fixed.count('(') == fixed.count(')')
		assert "`div[role='button'][aria-label='Click me']`" in fixed

	def test_escaped_quotes(self):
		"""Test double-escaped quotes."""
		tools = Tools()
		code = 'document.querySelector("div[data=\\"value\\"]")'
		fixed = tools._validate_and_fix_javascript(code)
		# Should fix escaped quotes
		assert '\\"' not in fixed or fixed.count('\\"') < code.count('\\"')

	def test_no_changes_needed(self):
		"""Test code that doesn't need fixing."""
		tools = Tools()
		code = 'var x = 1 + 2; console.log("hello");'
		fixed = tools._validate_and_fix_javascript(code)
		# Should remain mostly the same (might fix escaped quotes)
		assert fixed.count('(') == fixed.count(')')

	def test_template_literal_already_present(self):
		"""Test code that already uses template literals."""
		tools = Tools()
		code = 'document.querySelector(`div[role="button"]`)'
		fixed = tools._validate_and_fix_javascript(code)
		# Should not break existing template literals
		assert '`div[role="button"]`' in fixed
		assert fixed.count('(') == fixed.count(')')

	def test_querySelector_with_whitespace(self):
		"""Test querySelector with whitespace around parentheses."""
		tools = Tools()
		code = 'document.querySelector ( "div[role=\'button\']" )'
		fixed = tools._validate_and_fix_javascript(code)
		assert fixed.count('(') == fixed.count(')')
		assert "querySelector(`div[role='button']`)" in fixed.replace(' ', '')

	def test_chained_calls(self):
		"""Test chained method calls."""
		tools = Tools()
		code = 'document.querySelector("div[role=\'button\']").classList.add("active");'
		fixed = tools._validate_and_fix_javascript(code)
		assert fixed.count('(') == fixed.count(')')
		assert "querySelector(`div[role='button']`)" in fixed

	def test_arrow_function(self):
		"""Test arrow function with querySelector."""
		tools = Tools()
		code = '() => document.querySelector("div[role=\'button\']")'
		fixed = tools._validate_and_fix_javascript(code)
		assert fixed.count('(') == fixed.count(')')
		assert "querySelector(`div[role='button']`)" in fixed

	def test_immediately_invoked_function(self):
		"""Test IIFE with querySelector."""
		tools = Tools()
		code = '(function() { return document.querySelector("div[role=\'button\']"); })()'
		fixed = tools._validate_and_fix_javascript(code)
		assert fixed.count('(') == fixed.count(')')
		assert "querySelector(`div[role='button']`)" in fixed

	def test_querySelector_with_complex_nested_quotes(self):
		"""Test querySelector with deeply nested quote scenarios."""
		tools = Tools()
		code = 'document.querySelector("div[data-attr=\'value with \\"escaped\\" quotes\']")'
		fixed = tools._validate_and_fix_javascript(code)
		assert fixed.count('(') == fixed.count(')')

	def test_querySelectorAll_in_loop(self):
		"""Test querySelectorAll in a loop."""
		tools = Tools()
		code = 'for (let i = 0; i < 10; i++) { document.querySelectorAll("div[role=\'item\'][index=\'" + i + "\']"); }'
		fixed = tools._validate_and_fix_javascript(code)
		assert fixed.count('(') == fixed.count(')')

	def test_preserve_other_code_structure(self):
		"""Test that other code structure is preserved."""
		tools = Tools()
		code = """
		function test() {
			var x = document.querySelector("div[role='button']");
			if (x) {
				return x.getAttribute('data-value');
			}
			return null;
		}
		"""
		fixed = tools._validate_and_fix_javascript(code)
		# Should preserve function structure
		assert 'function test()' in fixed
		assert 'if (x)' in fixed
		assert fixed.count('{') == fixed.count('}')
		assert fixed.count('(') == fixed.count(')')
