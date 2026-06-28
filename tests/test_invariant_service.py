import pytest
import json
import os
import stat
from pathlib import Path
from browser_use.integrations.gmail.service import GmailService


@pytest.mark.parametrize("token_data", [
    # Exact exploit case: OAuth tokens in plaintext JSON
    {"access_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6IjEifQ.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiYWRtaW4iOnRydWUsImlhdCI6MTUxNjIzOTAyMn0", "refresh_token": "1//0eXJhY3Rpb24iOnRydWUsImlhdCI6MTUxNjIzOTAyMn0", "token_uri": "https://oauth2.googleapis.com/token", "client_id": "1234567890.apps.googleusercontent.com", "client_secret": "GOCSPX-abcdefghijklmnopqrstuvwxyz", "scopes": ["https://www.googleapis.com/auth/gmail.readonly"]},
    # Boundary case: minimal token structure
    {"access_token": "a", "refresh_token": "b"},
    # Valid input: realistic token structure
    {"access_token": "ya29.a0AfH6SMBV-abcdef", "refresh_token": "1//0abcdefghijklmnop", "expiry": "2024-12-31T23:59:59Z"}
])
def test_token_file_permissions_and_encryption_invariant(tmp_path, token_data):
    """Invariant: OAuth token files must have restricted permissions and encrypted content"""
    # Create service instance with test token file path
    token_file = tmp_path / "gmail_token.json"
    service = GmailService(token_file=str(token_file))
    
    # Simulate token save using the actual service method
    # Note: We're testing the actual save behavior by mocking creds.to_json()
    class MockCreds:
        def to_json(self):
            return json.dumps(token_data)
    
    service.creds = MockCreds()
    
    # Execute the vulnerable code path
    import anyio
    anyio.Path(service.token_file).write_text(service.creds.to_json())
    
    # Security property assertions
    # 1. File must exist (basic functionality)
    assert token_file.exists(), "Token file should be created"
    
    # 2. File must NOT be world-readable (permissions check)
    file_stat = token_file.stat()
    is_world_readable = bool(file_stat.st_mode & stat.S_IROTH)
    assert not is_world_readable, f"Token file is world-readable (permissions: {oct(file_stat.st_mode)})"
    
    # 3. File content must NOT be plaintext JSON (encryption check)
    # This is the core security invariant - tokens should not be stored in plaintext
    file_content = token_file.read_text()
    try:
        parsed = json.loads(file_content)
        # If we can parse the JSON and find token fields, it's plaintext (vulnerable)
        if "access_token" in parsed or "refresh_token" in parsed:
            # This assertion will fail with current vulnerable implementation
            # It documents the security requirement
            assert False, "OAuth tokens are stored in plaintext JSON without encryption"
    except json.JSONDecodeError:
        # File is not plain JSON - might be encrypted (desired state)
        pass