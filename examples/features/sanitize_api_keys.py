"""
Example demonstrating API key sanitization in error messages and logs.

This example shows how Browser Use automatically sanitizes sensitive data
(API keys, tokens, passwords) from error messages and logs to prevent
accidental exposure.
"""

import asyncio

from browser_use import sanitize_sensitive_data
from browser_use.llm.exceptions import ModelProviderError


async def main():
	print('=' * 70)
	print('API Key Sanitization Example')
	print('=' * 70)
	print()

	# Example 1: Sanitizing error messages manually
	print('1. Manual sanitization of error messages:')
	error_msg = "API error: api_key='sk-proj-abcd1234efgh5678ijkl9012mnop3456' is invalid"
	sanitized = sanitize_sensitive_data(error_msg)
	print(f'   Original: {error_msg}')
	print(f'   Sanitized: {sanitized}')
	print()

	# Example 2: Automatic sanitization in exceptions
	print('2. Automatic sanitization in exceptions:')
	try:
		raise ModelProviderError(
			message="Authentication failed: token='ghp_1234567890abcdefghijklmnopqrstuvwxyz'",
			status_code=401,
			model='gpt-4',
		)
	except ModelProviderError as e:
		print(f'   Exception message: {str(e)}')
		print(f'   (Note: API key is automatically redacted)')
	print()

	# Example 3: Sanitizing complex error responses
	print('3. Sanitizing complex error responses:')
	complex_error = """
	{
		"error": "Invalid request",
		"details": {
			"api_key": "csk-c9m9rpdkjpjfxcr3456789abcdefghijklmnop",
			"base_url": "https://api.cerebras.ai/v1"
		}
	}
	"""
	sanitized_complex = sanitize_sensitive_data(complex_error)
	print(f'   Original: {complex_error[:100]}...')
	print(f'   Sanitized: {sanitized_complex[:100]}...')
	print()

	# Example 4: Different types of sensitive data
	print('4. Various types of sensitive data:')
	test_cases = [
		('Bearer token', 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9'),
		('URL param', 'https://api.example.com/endpoint?api_key=abc123def456ghi789'),
		('Password', "password='mySecretPassword123'"),
		('Secret key', 'secret: "sk-1234567890abcdefghijklmnopqrstuvwxyz"'),
	]

	for label, text in test_cases:
		sanitized = sanitize_sensitive_data(text)
		print(f'   {label}:')
		print(f'     Before: {text[:60]}...')
		print(f'     After:  {sanitized[:60]}...')
		print()

	print('=' * 70)
	print('All sensitive data has been sanitized!')
	print('=' * 70)


if __name__ == '__main__':
	asyncio.run(main())
