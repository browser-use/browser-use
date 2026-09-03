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
		super().__init__(message)
		self.message = message
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


class ModelOutputTruncatedError(ModelProviderError):
	"""Output was cut off at an output-token limit (finish_reason='length' / stop_reason='max_tokens').

	Status 400 keeps it out of same-provider retry loops; the agent's fallback switch treats it as recoverable.
	"""

	def __init__(
		self,
		message: str,
		model: str | None = None,
	):
		super().__init__(message, status_code=400, model=model)
