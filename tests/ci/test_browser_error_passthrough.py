"""Regression test: BrowserError raised inside an action must reach Tools.act with its
structured short/long-term memory intact, instead of being flattened into a generic
'Error executing action ...' RuntimeError by execute_action's catch-all handler."""

from browser_use.browser.views import BrowserError
from browser_use.tools.service import Tools


async def test_browser_error_memory_survives_execute_action():
	tools = Tools()

	@tools.registry.action(description='Test action that raises a structured BrowserError')
	async def raise_structured_error():
		raise BrowserError(
			message='element is a select, not clickable',
			short_term_memory='Available options: alpha, beta, gamma',
			long_term_memory='Tried to click a dropdown; use select_dropdown instead',
		)

	ActionModel = tools.registry.create_action_model()
	action = ActionModel(**{'raise_structured_error': {}})

	result = await tools.act(action, browser_session=None)  # type: ignore[arg-type] -- action doesn't touch the browser

	assert result.error == 'Tried to click a dropdown; use select_dropdown instead', (
		f'structured long_term_memory lost: {result.error!r}'
	)
	assert result.extracted_content == 'Available options: alpha, beta, gamma'


async def test_plain_browser_error_still_returns_recoverable_action_result():
	"""A BrowserError without long_term_memory must not escape Tools.act as an
	exception — it must still come back as a recoverable ActionResult (as it did
	when the generic execute_action handler flattened it)."""
	tools = Tools()

	@tools.registry.action(description='Test action that raises a plain BrowserError')
	async def raise_plain_error():
		raise BrowserError(message='element with index 5 does not exist')

	ActionModel = tools.registry.create_action_model()
	action = ActionModel(**{'raise_plain_error': {}})

	result = await tools.act(action, browser_session=None)  # type: ignore[arg-type] -- action doesn't touch the browser

	assert result.error is not None and 'element with index 5 does not exist' in result.error
