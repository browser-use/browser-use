import re
from browser_use.sanitization.policy import DLPSanitizerConfig
from browser_use.sanitization.redactors import sanitize_text

def test_email_masking():
    cfg = DLPSanitizerConfig(enabled=True, mode="mask")
    text, findings = sanitize_text("Contact me at john.doe@example.com", cfg)
    assert "example.com" not in text
    assert any(f.type == "email" for f in findings)

def test_jwt_masking():
    cfg = DLPSanitizerConfig(enabled=True, mode="mask")
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NSJ9.sgnatureXXX"
    text, findings = sanitize_text(f"token={jwt}", cfg)
    assert jwt not in text
    assert any(f.type == "jwt" for f in findings)
