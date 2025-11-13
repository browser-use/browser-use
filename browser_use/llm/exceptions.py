from browser_use.utils import sanitize_sensitive_data


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
		sanitized_message = sanitize_sensitive_data(message)
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
		super().__init__(message, status_code, model)
