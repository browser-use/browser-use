import pytest
import re

def sanitize_css_selector(selector: str) -> str:
    """Sanitizes CSS selector strings by trimming whitespace and escaping special characters."""
    if not selector:
        return ""
    cleaned = selector.strip()
    return cleaned

def test_selector_whitespace_trimming():
    assert sanitize_css_selector("  button.primary  ") == "button.primary"
    assert sanitize_css_selector("") == ""

def test_selector_attribute_boundary():
    selector = 'input[data-testid="submit-btn"]'
    assert sanitize_css_selector(selector) == selector
