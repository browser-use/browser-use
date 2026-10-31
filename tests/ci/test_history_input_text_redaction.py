"""Regression test: `save_to_file` must redact sensitive data from the built-in `input_text` action.

`AgentHistory.model_dump` guarded the redaction with `'input' in action`, a dictionary key lookup on the
action name. The built-in action is named `input_text`, so the guard never matched and typed credentials were
written to disk in plaintext.
"""

import tempfile
from pathlib import Path
from typing import Any

from pydantic import create_model

from browser_use.agent.views import AgentHistory, AgentHistoryList, AgentOutput
from browser_use.browser.views import BrowserStateHistory
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.views import InputTextAction

SECRET = 'token-123'


def _history_with_input_text() -> AgentHistoryList:
	model = create_model('Model', __base__=ActionModel, input_text=(InputTextAction | None, None))
	output_model = AgentOutput.type_with_custom_actions(model)
	action = model(input_text=InputTextAction(index=1, text=SECRET))

	return AgentHistoryList[Any](
		history=[
			AgentHistory(
				model_output=output_model(memory='', action=[action]),
				result=[],
				state=BrowserStateHistory(url='https://example.test', title='t', tabs=[], interacted_element=[None]),
			)
		]
	)


def test_input_text_value_is_redacted_in_saved_history() -> None:
	path = Path(tempfile.mkdtemp()) / 'history.json'
	_history_with_input_text().save_to_file(path, sensitive_data={'api_key': SECRET})
	saved = path.read_text(encoding='utf-8')

	assert SECRET not in saved
	assert '<secret>api_key</secret>' in saved


def test_non_input_actions_keep_their_arguments() -> None:
	history = _history_with_input_text()
	dumped = history.history[0].model_dump(sensitive_data={'api_key': SECRET})

	for action in dumped['model_output']['action']:
		for action_name, params in action.items():
			if 'input' in action_name:
				continue
			assert SECRET not in str(params)
