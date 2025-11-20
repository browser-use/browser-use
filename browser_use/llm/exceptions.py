class ModelError(Exception):
	pass


class ModelProviderError(ModelError):
	"""Exception raised when a model provider returns an error."""

	def __init__(
		self,
		message: str,
		status_code: int = 502,
		model: str | None = None,
	):
		from browser_use.llm.sanitization import sanitize_string
		
		# Sanitize the message to remove any API keys
		sanitized_message = sanitize_string(message)
		super().__init__(sanitized_message)
		self.message = sanitized_message
		self.status_code = status_code
		self.model = model


class ModelRateLimitError(ModelProviderError):
	"""Exception raised when a model provider returns a rate limit error."""

	def __init__(
		self,
		message: str,
		status_code: int = 429,
		model: str | None = None,
	):
		# ModelProviderError will sanitize the message
		super().__init__(message, status_code, model)
