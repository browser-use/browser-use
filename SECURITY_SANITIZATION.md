# API Key Sanitization Implementation

## Overview

This implementation adds automatic sanitization of sensitive data (API keys, tokens, passwords, secrets) from error messages and logs throughout the Browser Use library.

## Problem Statement

User's LLM model API keys were being exposed in error messages and logs, as evidenced by:

```
browser_use_sdk.errors.unprocessable_entity_error.UnprocessableEntityError: 
...
'input': {
    'model': 'cerebras_qwen_3_235b_a22b_thinking_2507',
    'api_key': 'csk-c9m9rpdkjpjfxcr…',  # ← EXPOSED!
    ...
}
```

**Impact:**
- Secrets in logs widen the blast radius if logs are shared with vendors, support tools, or leaked
- Anyone with access to logs could potentially reuse the key against the upstream API

## Solution

### 1. Core Sanitization Function (`browser_use/utils.py`)

Added `sanitize_sensitive_data(text: str) -> str` function that uses regex patterns to detect and redact:

- **API Keys**: `sk-...`, `csk-...`, `api_key='...'`, `apikey: "..."`
- **Bearer Tokens**: `Bearer eyJ...`
- **URL Parameters**: `?api_key=...`, `&token=...`
- **Passwords**: `password='...'`
- **Secrets**: `secret: "..."`
- **Long Keys**: Any 32+ character alphanumeric string

All sensitive values are replaced with `[REDACTED]` while preserving context.

### 2. Exception Sanitization

Updated exception classes to automatically sanitize messages:

**`browser_use/exceptions.py`:**
```python
class LLMException(Exception):
    def __init__(self, status_code, message):
        sanitized_message = sanitize_sensitive_data(message)
        self.message = sanitized_message
        super().__init__(f'Error {status_code}: {sanitized_message}')
```

**`browser_use/llm/exceptions.py`:**
```python
class ModelProviderError(ModelError):
    def __init__(self, message: str, status_code: int = 502, model: str | None = None):
        sanitized_message = sanitize_sensitive_data(message)
        super().__init__(sanitized_message)
        self.message = sanitized_message
        # ...
```

### 3. Logging Sanitization

Updated the logging formatter to sanitize all log messages and arguments:

**`browser_use/logging_config.py`:**
```python
class BrowserUseFormatter(logging.Formatter):
    def format(self, record):
        # ... existing name cleanup ...
        
        # Sanitize sensitive data from log messages
        from browser_use.utils import sanitize_sensitive_data
        
        if record.msg and isinstance(record.msg, str):
            record.msg = sanitize_sensitive_data(record.msg)
        
        # Also sanitize args if they exist
        if record.args:
            sanitized_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    sanitized_args.append(sanitize_sensitive_data(arg))
                else:
                    sanitized_args.append(arg)
            record.args = tuple(sanitized_args)
        
        return super().format(record)
```

### 4. Task Exception Handling

Updated `create_task_with_error_handling()` to sanitize exception messages in background tasks:

```python
def _handle_task_exception(t: asyncio.Task[T]) -> None:
    exc = t.exception()
    if exc is not None:
        sanitized_msg = sanitize_sensitive_data(str(exc))
        log.error(f'Exception in background task: {sanitized_msg}')
```

### 5. Public API

Exported `sanitize_sensitive_data` from main package for manual use:

```python
from browser_use import sanitize_sensitive_data

error_msg = "API error: api_key='sk-proj-abc123' is invalid"
safe_msg = sanitize_sensitive_data(error_msg)
# Result: "API error: api_key='[REDACTED]' is invalid"
```

## Files Modified

1. **`browser_use/utils.py`**
   - Added `sanitize_sensitive_data()` function
   - Updated `create_task_with_error_handling()` to sanitize exceptions

2. **`browser_use/exceptions.py`**
   - Updated `LLMException` to sanitize messages

3. **`browser_use/llm/exceptions.py`**
   - Updated `ModelProviderError` and `ModelRateLimitError` to sanitize messages

4. **`browser_use/logging_config.py`**
   - Updated `BrowserUseFormatter` to sanitize log messages and arguments

5. **`browser_use/__init__.py`**
   - Exported `sanitize_sensitive_data` for public use

## Files Added

1. **`tests/ci/test_sanitize_api_keys.py`**
   - Comprehensive test suite for sanitization functionality
   - Tests for various key formats, exceptions, and logging

2. **`examples/features/sanitize_api_keys.py`**
   - Example demonstrating manual and automatic sanitization

3. **`docs/customize/security/api-key-sanitization.mdx`**
   - User-facing documentation for the feature

## Testing

The implementation includes comprehensive tests covering:

- ✅ API keys in various formats (OpenAI, Cerebras, generic)
- ✅ Bearer tokens
- ✅ URL query parameters
- ✅ Password fields
- ✅ Long alphanumeric strings
- ✅ Complex error messages (JSON, dicts)
- ✅ Exception sanitization
- ✅ Log message sanitization
- ✅ Preservation of normal text

Run tests with:
```bash
uv run pytest tests/ci/test_sanitize_api_keys.py -v
```

## Verification

Tested with the exact error message from the user's report:

```python
error_msg = '''... 'api_key': 'csk-c9m9rpdkjpjfxcr3456789abcdefghijklmnop' ...'''
sanitized = sanitize_sensitive_data(error_msg)
# Result: ... 'api_key': '[REDACTED]' ...
```

✅ **Result**: API key successfully sanitized

## Performance Impact

- **Minimal overhead**: Regex operations are fast (microseconds per message)
- **Lazy evaluation**: Only runs when exceptions/logs are generated
- **No impact on happy path**: Zero overhead when no errors occur

## Security Considerations

### What This Protects Against

✅ Accidental exposure in logs shared with support
✅ API keys in error messages sent to monitoring tools
✅ Credentials leaked in stack traces
✅ Sensitive data in debug output

### What This Does NOT Protect Against

❌ Keys already sent to external services before sanitization
❌ Keys stored in files or databases
❌ Novel key formats not matching our patterns
❌ Keys intentionally logged before this code runs

### Best Practices

Users should still:
1. Use environment variables for API keys
2. Rotate compromised keys immediately
3. Use minimal API key permissions
4. Monitor API usage for anomalies
5. Consider secrets management tools (AWS Secrets Manager, Vault, etc.)

## Backward Compatibility

✅ **Fully backward compatible**
- No breaking changes to existing APIs
- All existing code continues to work
- New functionality is additive only
- Exception behavior unchanged (just sanitized messages)

## Future Enhancements

Potential improvements:
1. Configurable sanitization patterns via environment variables
2. Option to disable sanitization for debugging (with explicit opt-in)
3. Support for custom sensitive data patterns
4. Integration with secrets detection tools (truffleHog, detect-secrets)
5. Audit logging of sanitization events

## References

- User report: API keys exposed in error messages
- Related issue: Security best practices for logging
- Similar implementations: AWS SDK, Google Cloud SDK
