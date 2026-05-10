import pytest
from pydantic import ValidationError

from browser_use.tools.views import InputTextAction


def test_input_text_index_rejects_boolean_values():
	"""Boolean indexes should not be coerced to element indexes."""
	with pytest.raises(ValidationError):
		InputTextAction.model_validate({'index': True, 'text': 'hello'})

	with pytest.raises(ValidationError):
		InputTextAction.model_validate({'index': False, 'text': 'hello'})


def test_input_text_index_accepts_integers():
	assert InputTextAction.model_validate({'index': 0, 'text': 'hello'}).index == 0
	assert InputTextAction.model_validate({'index': 3, 'text': 'hello'}).index == 3
