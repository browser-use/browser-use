from typing import Optional


class ModelError(Exception):
	pass


class ModelProviderError(ModelError):
	"""Exception raised when a model provider returns an error."""

	def __init__(
		self,
		message: str,
		status_code: int = 502,
		model_name: Optional[str] = None,
	):
		super().__init__(message, status_code)
		self.model_name = model_name


class ModelRateLimitError(ModelProviderError):
	"""Exception raised when a model provider returns a rate limit error."""

	def __init__(
		self,
		message: str,
		status_code: int = 429,
		model_name: Optional[str] = None,
	):
		super().__init__(message, status_code, model_name)
