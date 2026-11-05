class MissingAPIKeyError(RuntimeError):
	"""No usable Browser Use API key for the default model or the default cloud browser."""

	def __init__(self, what: str = 'Browser Use Cloud', *, v3_only: bool = False):
		if v3_only:
			message = (
				f'{what} needs a Browser Use API key with v4 access; the stored key is from an older login and only '
				'starts v3 browsers. Run `browser-use login` again (or set BROWSER_USE_API_KEY).'
			)
		else:
			message = (
				f'{what} needs a Browser Use API key. Run `browser-use login` (opens your browser; the key it stores '
				'works for the library, the CLI, the MCP server and browser-harness), or set BROWSER_USE_API_KEY. No key: '
				'use a local browser and your own model: Agent(task, llm=ChatOpenAI(...), browser=Browser(local=True)).'
			)
		super().__init__(message)
