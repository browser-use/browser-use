"""Element-index actions must reject index 0, matching click."""

import pytest
from pydantic import ValidationError

from browser_use.tools.views import (
	GetDropdownOptionsAction,
	InputTextAction,
	SelectDropdownOptionAction,
	UploadFileAction,
)


def test_input_rejects_index_zero():
	with pytest.raises(ValidationError):
		InputTextAction(index=0, text='x')


def test_dropdown_options_rejects_index_zero():
	with pytest.raises(ValidationError):
		GetDropdownOptionsAction(index=0)


def test_select_dropdown_rejects_index_zero():
	with pytest.raises(ValidationError):
		SelectDropdownOptionAction(index=0, text='A')


def test_upload_file_rejects_index_zero():
	with pytest.raises(ValidationError):
		UploadFileAction(index=0, path='resume.pdf')


@pytest.mark.parametrize(
	'action',
	[
		lambda: InputTextAction(index=1, text='x'),
		lambda: GetDropdownOptionsAction(index=1),
		lambda: SelectDropdownOptionAction(index=1, text='A'),
		lambda: UploadFileAction(index=1, path='resume.pdf'),
	],
	ids=['input', 'dropdown_options', 'select_dropdown', 'upload_file'],
)
def test_actions_accept_index_one(action):
	assert action().index == 1
