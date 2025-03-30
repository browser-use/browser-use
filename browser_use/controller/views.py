from typing import Optional

from pydantic import BaseModel, Field, model_validator


# Action Input Models
class SearchGoogleAction(BaseModel):
	query: str


class GoToUrlAction(BaseModel):
	url: str


class WaitForElementAction(BaseModel):
	selector: str
	timeout: Optional[int] = 10000  # Timeout in milliseconds


class ClickElementAction(BaseModel):
	index: int
	xpath: Optional[str] = None


class ClickElementByXpathAction(BaseModel):
	xpath: str


class ClickElementBySelectorAction(BaseModel):
	css_selector: str


class ClickElementByTextAction(BaseModel):
	text: str
	element_type: Optional[str]
	nth: int = 0


class InputTextAction(BaseModel):
	index: int
	text: str
	xpath: Optional[str] = None


class DoneAction(BaseModel):
	text: str
	success: bool


class SwitchTabAction(BaseModel):
	page_id: int


class OpenTabAction(BaseModel):
	url: str


class CloseTabAction(BaseModel):
	page_id: int


class ScrollAction(BaseModel):
	amount: Optional[int] = None  # The number of pixels to scroll. If None, scroll down/up one page


class SendKeysAction(BaseModel):
	keys: str


class GroupTabsAction(BaseModel):
	tab_ids: list[int] = Field(..., description='List of tab IDs to group')
	title: str = Field(..., description='Name for the tab group')
	color: Optional[str] = Field(
		'blue',
		description='Color for the group (grey/blue/red/yellow/green/pink/purple/cyan)',
	)


class UngroupTabsAction(BaseModel):
	tab_ids: list[int] = Field(..., description='List of tab IDs to ungroup')


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
