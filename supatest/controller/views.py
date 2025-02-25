from typing import Optional, Union, Literal

from pydantic import BaseModel, model_validator

# Action Input Models
class GoToUrlAction(BaseModel):
    url: str


class ClickElementAction(BaseModel):
    index: int
    xpath: Optional[str] = None
    supatest_locator_id: Optional[str] = None


class InputTextAction(BaseModel):
    index: int
    text: str
    xpath: Optional[str] = None
    supatest_locator_id: Optional[str] = None


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


class SelectDropdownOptionAction(BaseModel):
    index: int
    text: str
    xpath: Optional[str] = None
    supatest_locator_id: Optional[str] = None


class GetDropdownOptionsAction(BaseModel):
    index: int
    xpath: Optional[str] = None
    supatest_locator_id: Optional[str] = None


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


# Action Type Enum and Union
ActionType = Literal[
    'goto',
    'click',
    'input',
    'done',
    'switch_tab',
    'open_tab',
    'scroll',
    'send_keys',
    'extract_page_content',
    'select_dropdown_option',
    'get_dropdown_options',
    'back',
    'forward',
    'refresh',
]

Action = Union[
    GoToUrlAction,
    ClickElementAction,
    InputTextAction,
    DoneAction,
    SwitchTabAction,
    OpenTabAction,
    ScrollAction,
    SendKeysAction,
    ExtractPageContentAction,
    SelectDropdownOptionAction,
    GetDropdownOptionsAction,
    NoParamsAction,
]


# Action Request Model
class ActionRequest(BaseModel):
    type: ActionType
    data: Action 