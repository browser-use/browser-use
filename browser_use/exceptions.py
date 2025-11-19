from browser_use.utils import sanitize_sensitive_data


class LLMException(Exception):
	def __init__(self, status_code, message):
		self.status_code = status_code
		sanitized_message = sanitize_sensitive_data(message)
		self.message = sanitized_message
		super().__init__(f'Error {status_code}: {sanitized_message}')
