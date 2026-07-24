from unittest.mock import Mock

import browser_use.tools.views as tool_views
from browser_use.tools.views import InputTextAction


def test_input_text_action_warns_on_boolean_index(monkeypatch):
	warning = Mock()
	monkeypatch.setattr(tool_views.logger, 'warning', warning)

	params = InputTextAction.model_validate({'index': True, 'text': 'email'})

	assert params.index == 1
	warning.assert_called_once()
	assert 'Coercing boolean input_text index %s to %d' in warning.call_args.args[0]
	assert warning.call_args.args[1:] == (True, 1)
