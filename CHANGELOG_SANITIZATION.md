# API Key Sanitization - Changelog Entry

## Security Enhancement: Automatic API Key Sanitization

### Added

- **Automatic sanitization of sensitive data** in error messages and logs
  - API keys (OpenAI, Cerebras, generic formats)
  - Bearer tokens and access tokens
  - Passwords and secrets
  - Authorization headers
  - URL query parameters with sensitive data

- **New utility function**: `sanitize_sensitive_data(text: str) -> str`
  - Exported from main `browser_use` package
  - Can be used manually to sanitize any text
  - Uses regex patterns to detect and redact sensitive information

- **Automatic sanitization in exceptions**
  - `LLMException` now sanitizes error messages
  - `ModelProviderError` now sanitizes error messages
  - `ModelRateLimitError` inherits sanitization from parent

- **Automatic sanitization in logging**
  - `BrowserUseFormatter` now sanitizes all log messages
  - Log arguments are also sanitized
  - Works across all log levels (DEBUG, INFO, WARNING, ERROR)

- **Automatic sanitization in background tasks**
  - `create_task_with_error_handling()` sanitizes exception messages

### Changed

- Error messages now show `[REDACTED]` instead of actual API keys
- Log output now automatically redacts sensitive data
- Exception messages preserve structure but hide sensitive values

### Security Impact

**Before:**
```python
# Error message exposed API key
UnprocessableEntityError: ... 'api_key': 'csk-c9m9rpdkjpjfxcr3456789...' ...
```

**After:**
```python
# Error message sanitizes API key
UnprocessableEntityError: ... 'api_key': '[REDACTED]' ...
```

### Usage

**Automatic (no code changes needed):**
```python
from browser_use import Agent, ChatOpenAI

# All errors and logs are automatically sanitized
agent = Agent(
    task="Your task",
    llm=ChatOpenAI(api_key="sk-proj-SENSITIVE")
)
```

**Manual sanitization:**
```python
from browser_use import sanitize_sensitive_data

error = "API error: api_key='sk-proj-abc123' is invalid"
safe = sanitize_sensitive_data(error)
print(safe)  # "API error: api_key='[REDACTED]' is invalid"
```

### Files Modified

- `browser_use/utils.py` - Added sanitization function
- `browser_use/exceptions.py` - Added sanitization to LLMException
- `browser_use/llm/exceptions.py` - Added sanitization to ModelProviderError
- `browser_use/logging_config.py` - Added sanitization to log formatter
- `browser_use/__init__.py` - Exported sanitize_sensitive_data

### Files Added

- `tests/ci/test_sanitize_api_keys.py` - Comprehensive test suite
- `examples/features/sanitize_api_keys.py` - Usage examples
- `docs/customize/security/api-key-sanitization.mdx` - Documentation
- `SECURITY_SANITIZATION.md` - Implementation details

### Backward Compatibility

✅ **Fully backward compatible**
- No breaking changes
- All existing code continues to work
- Exception behavior unchanged (just sanitized messages)
- No performance impact on happy path

### Testing

Run tests with:
```bash
uv run pytest tests/ci/test_sanitize_api_keys.py -v
```

### Performance

- **Minimal overhead**: Regex operations are fast (microseconds)
- **Lazy evaluation**: Only runs when errors/logs are generated
- **Zero impact on success path**: No overhead when no errors occur

### Known Limitations

- Novel key formats may not be detected
- Cannot sanitize data already sent to external services
- False negatives possible with unusual formats
- Intentional to avoid false positives (e.g., model names)

### Recommendations

While sanitization helps prevent accidental exposure, users should still:
1. Use environment variables for API keys
2. Rotate compromised keys immediately
3. Use minimal API key permissions
4. Monitor API usage for anomalies
5. Consider secrets management tools (AWS Secrets Manager, Vault, etc.)

### Related Issues

- Fixes: User report of API keys exposed in error messages
- Addresses: Security concern about log sharing with vendors
- Improves: Overall security posture of the library

### Migration Guide

No migration needed - sanitization is automatic and transparent.

### Credits

Implemented in response to user security report about API key exposure in error logs.
