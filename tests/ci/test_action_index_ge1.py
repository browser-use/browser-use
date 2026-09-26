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


def test_input_accepts_index_one():
	assert InputTextAction(index=1, text='x').index == 1
