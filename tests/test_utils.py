"""Unit tests for browser_use.utils."""

import pytest
from browser_use.utils import collect_sensitive_data_values, redact_sensitive_string


class TestCollectSensitiveDataValues:
    """Tests for collect_sensitive_data_values."""

    def test_returns_empty_dict_for_none(self):
        assert collect_sensitive_data_values(None) == {}

    def test_returns_empty_dict_for_empty(self):
        assert collect_sensitive_data_values({}) == {}

    def test_flat_format(self):
        result = collect_sensitive_data_values({"token": "abc123", "key": "xyz"})
        assert result == {"token": "abc123", "key": "xyz"}

    def test_domain_scoped_format_single_domain(self):
        result = collect_sensitive_data_values(
            {"example.com": {"username": "alice", "password": "s3cr3t"}}
        )
        assert result == {
            "example.com:username": "alice",
            "example.com:password": "s3cr3t",
        }

    def test_domain_scoped_format_multiple_domains_same_key_names(self):
        """Credentials with the same key name across domains must not overwrite each other.

        Previously, iterating over domain-scoped entries wrote ``sensitive_values[key] = val``
        directly, so whichever domain was iterated last would silently overwrite earlier ones.
        A ``password`` belonging to ``site-a.com`` would be lost when ``site-b.com``'s
        ``password`` was processed next — meaning ``site-a.com``'s secret was never redacted.
        """
        sensitive_data = {
            "site-a.com": {"token": "token-aaa", "password": "pass-aaa"},
            "site-b.com": {"token": "token-bbb", "password": "pass-bbb"},
        }
        result = collect_sensitive_data_values(sensitive_data)

        # All four secrets must be present under their namespaced keys
        assert result["site-a.com:token"] == "token-aaa"
        assert result["site-a.com:password"] == "pass-aaa"
        assert result["site-b.com:token"] == "token-bbb"
        assert result["site-b.com:password"] == "pass-bbb"
        assert len(result) == 4

    def test_domain_scoped_skips_empty_values(self):
        result = collect_sensitive_data_values(
            {"example.com": {"username": "alice", "password": ""}}
        )
        assert "example.com:password" not in result
        assert result == {"example.com:username": "alice"}

    def test_mixed_flat_and_domain_scoped(self):
        sensitive_data = {
            "api_key": "flat-secret",
            "site.com": {"token": "domain-secret"},
        }
        result = collect_sensitive_data_values(sensitive_data)
        assert result["api_key"] == "flat-secret"
        assert result["site.com:token"] == "domain-secret"


class TestRedactSensitiveString:
    """Tests for redact_sensitive_string."""

    def test_redacts_all_collected_secrets(self):
        sensitive_data = {
            "site-a.com": {"token": "token-aaa"},
            "site-b.com": {"token": "token-bbb"},
        }
        sensitive_values = collect_sensitive_data_values(sensitive_data)
        log_line = "Calling site-a with token-aaa and site-b with token-bbb"
        redacted = redact_sensitive_string(log_line, sensitive_values)
        assert "token-aaa" not in redacted
        assert "token-bbb" not in redacted

    def test_no_false_redaction_for_unrelated_text(self):
        sensitive_values = collect_sensitive_data_values({"key": "hunter2"})
        log_line = "The user typed something else entirely"
        assert redact_sensitive_string(log_line, sensitive_values) == log_line
