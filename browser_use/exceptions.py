class MissingAPIKeyError(RuntimeError):
	"""No Browser Use API key for the default model or the default cloud browser."""

	def __init__(self, what: str = 'Browser Use Cloud'):
		super().__init__(
			f'{what} needs a Browser Use API key. Run `browser-use auth login` (or set BROWSER_USE_API_KEY), '
			"or use a local browser and your own model: Agent(task, llm=ChatOpenAI(...), browser=Browser('chromium'))."
		)
