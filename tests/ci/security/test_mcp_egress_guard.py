from browser_use.mcp.server import mcp_sanitize_egress


def test_mcp_egress_guard_non_mutating():
    payload = {"text": "email: alice@example.com", "list": ["token=eyJbogus.bogus.sgn"], "nested": {"k": "ssn 123-45-6789"}}
    original = payload.copy()
    sanitized, meta = mcp_sanitize_egress(payload)
    assert payload == original  # non-mutating
    assert meta["sanitized"] is True
    assert meta["dlp_findings"] >= 1
    # Ensure obvious secrets masked
    assert "example.com" not in str(sanitized)
