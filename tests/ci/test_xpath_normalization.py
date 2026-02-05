"""
Tests for XPath attribute normalization utility.

These tests verify that normalize_xpath_attributes correctly handles
LLM-generated XPath with incorrectly cased attribute names.
"""

import pytest

from browser_use.utils import normalize_xpath_attributes


class TestXPathNormalization:
	"""Test XPath attribute case normalization."""

	def test_single_uppercase_attribute(self):
		"""Test normalization of single uppercase attribute."""
		xpath = "//div[@ROLE='button']"
		expected = "//div[@role='button']"
		assert normalize_xpath_attributes(xpath) == expected

	def test_mixed_case_attribute(self):
		"""Test normalization of mixed case attribute."""
		xpath = "//div[@Class='test']"
		expected = "//div[@class='test']"
		assert normalize_xpath_attributes(xpath) == expected

	def test_multiple_attributes(self):
		"""Test normalization of multiple attributes."""
		xpath = "//div[@ID='x'][@Name='y']"
		expected = "//div[@id='x'][@name='y']"
		assert normalize_xpath_attributes(xpath) == expected

	def test_preserve_attribute_values(self):
		"""Test that attribute values remain unchanged."""
		xpath = "//div[@role='BUTTON']"
		expected = "//div[@role='BUTTON']"
		assert normalize_xpath_attributes(xpath) == expected

	def test_aria_attributes(self):
		"""Test normalization of ARIA attributes."""
		xpath = "//div[@ARIA-LABEL='Submit'][@ARIA-HIDDEN='false']"
		expected = "//div[@aria-label='Submit'][@aria-hidden='false']"
		assert normalize_xpath_attributes(xpath) == expected

	def test_data_attributes(self):
		"""Test normalization of data-* attributes."""
		xpath = "//div[@DATA-ID='123'][@Data-Value='test']"
		expected = "//div[@data-id='123'][@data-value='test']"
		assert normalize_xpath_attributes(xpath) == expected

	def test_already_lowercase(self):
		"""Test that already correct XPath is unchanged."""
		xpath = "//div[@role='button'][@class='btn']"
		expected = "//div[@role='button'][@class='btn']"
		assert normalize_xpath_attributes(xpath) == expected

	def test_complex_xpath(self):
		"""Test normalization in complex XPath expression."""
		xpath = "//div[@ROLE='columnheader']//div[contains(@Class,'oxd-table-header-cell-text')]"
		expected = "//div[@role='columnheader']//div[contains(@class,'oxd-table-header-cell-text')]"
		assert normalize_xpath_attributes(xpath) == expected

	def test_xpath_with_text(self):
		"""Test XPath with text() function."""
		xpath = "//div[@ROLE='button' and text()='Submit']"
		expected = "//div[@role='button' and text()='Submit']"
		assert normalize_xpath_attributes(xpath) == expected

	def test_xpath_with_position(self):
		"""Test XPath with position predicates."""
		xpath = "//div[@Class='container'][1]//span[@ID='label']"
		expected = "//div[@class='container'][1]//span[@id='label']"
		assert normalize_xpath_attributes(xpath) == expected

	def test_empty_string(self):
		"""Test handling of empty string."""
		assert normalize_xpath_attributes('') == ''

	def test_xpath_without_attributes(self):
		"""Test XPath without attributes."""
		xpath = '//div/span/a'
		expected = '//div/span/a'
		assert normalize_xpath_attributes(xpath) == expected

	def test_mixed_operators(self):
		"""Test XPath with various operators."""
		xpath = "//input[@Type='text' or @Type='email'][@Required='true']"
		expected = "//input[@type='text' or @type='email'][@required='true']"
		assert normalize_xpath_attributes(xpath) == expected

	def test_attribute_with_numbers(self):
		"""Test attribute names containing numbers."""
		xpath = "//input[@Data-Step2='active']"
		expected = "//input[@data-step2='active']"
		assert normalize_xpath_attributes(xpath) == expected

	def test_preserve_uppercase_values_in_contains(self):
		"""Test that uppercase values in contains() are preserved."""
		xpath = "//div[contains(@class,'UPPERCASE-CLASS')]"
		expected = "//div[contains(@class,'UPPERCASE-CLASS')]"
		assert normalize_xpath_attributes(xpath) == expected

	def test_real_world_example_from_bug_report(self):
		"""Test the actual example from GitHub issue #4003."""
		xpath = "//div[@ROLE='columnheader']//div[contains(@Class,'oxd-table-header-cell-text') and text()='Job Titles']"
		expected = "//div[@role='columnheader']//div[contains(@class,'oxd-table-header-cell-text') and text()='Job Titles']"
		assert normalize_xpath_attributes(xpath) == expected


if __name__ == '__main__':
	pytest.main([__file__, '-v'])
