class LLMException(Exception):
	def __init__(self, status_code, message, retriable=True):
		self.status_code = status_code
		self.message = message
		self.retriable = retriable  # Flag to indicate if this error can be retried
		super().__init__(f'Error {status_code}: {message}')
