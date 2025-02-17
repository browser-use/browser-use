from typing import List, Optional

from pydantic import BaseModel, model_validator


# Action Input Models
class SearchGoogleAction(BaseModel):
	query: str


class GoToUrlAction(BaseModel):
	url: str


class ClickElementAction(BaseModel):
	index: int
	xpath: Optional[str] = None

class OpenGoogleSpreadsheetAction(BaseModel):
    url: str
    
class ReadSpreadsheetAction(OpenGoogleSpreadsheetAction):
    pass

class AddRowAction(OpenGoogleSpreadsheetAction):
    pass

class InsertValueAction(OpenGoogleSpreadsheetAction):
    cell: str    # e.g., "B2"
    value: str

class InsertFunctionAction(OpenGoogleSpreadsheetAction):
    cell: str       # e.g., "C3"
    function: str   # e.g., "=SUM(A1:A10)"

class DeleteRowAction(OpenGoogleSpreadsheetAction):
    row: int   # The 1-indexed row number to delete
    
class DeleteRowsAction(OpenGoogleSpreadsheetAction):
    start_row: int   # The 1-indexed row number to delete
    end_row: int	 # The last row number to be deleted

class InputTextAction(BaseModel):
	index: int
	text: str
	xpath: Optional[str] = None


class DoneAction(BaseModel):
	text: str


class SwitchTabAction(BaseModel):
	page_id: int


class OpenTabAction(BaseModel):
	url: str


class ScrollAction(BaseModel):
	amount: Optional[int] = None  # The number of pixels to scroll. If None, scroll down/up one page


class SendKeysAction(BaseModel):
	keys: str

class ExtractPageContentAction(BaseModel):
    value: str
	
class NoParamsAction(BaseModel):
	"""
	Accepts absolutely anything in the incoming data
	and discards it, so the final parsed model is empty.
	"""

	@model_validator(mode='before')
	def ignore_all_inputs(cls, values):
		# No matter what the user sends, discard it and return empty.
		return {}

	class Config:
		# If you want to silently allow unknown fields at top-level,
		# set extra = 'allow' as well:
		extra = 'allow'
