from typing import Optional, Union, Literal
from pydantic import BaseModel, model_validator, Field
import uuid

# Action Input Models
class GoToUrlAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    url: str
    title: Optional[str] = Field(None, description="Human readable description of what this action does")
    isExecuted: str = Field(default='pending')

class GoBackAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: Optional[str] = Field(None, description="Human readable description of what this action does")
    isExecuted: str = Field(default='pending')

class WaitAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    seconds: int = 3
    title: Optional[str] = Field(None, description="Human readable description of what this action does")
    isExecuted: str = Field(default='pending')

class ClickElementAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    index: int
    xpath: Optional[str] = None
    title: Optional[str] = Field(None, description="Human readable description of what this action does")
    isExecuted: str = Field(default='pending')
    locator: Optional[str] = None
    allUniqueLocators: Optional[list[dict]] = None

class InputTextAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    index: int
    text: str
    xpath: Optional[str] = None
    title: Optional[str] = Field(None, description="Human readable description of what this action does")
    isExecuted: str = Field(default='pending')
    locator: Optional[str] = None
    allUniqueLocators: Optional[list[dict]] = None

class DoneAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    text: str
    success: bool
    title: Optional[str] = Field(None, description="Human readable description of what this action does")
    isExecuted: str = Field(default='pending')

class SwitchTabAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    page_id: int
    title: Optional[str] = Field(None, description="Human readable description of what this action does")
    isExecuted: str = Field(default='pending')

class OpenTabAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    url: str
    title: Optional[str] = Field(None, description="Human readable description of what this action does")
    isExecuted: str = Field(default='pending')

class ScrollAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    amount: Optional[int] = None  # The number of pixels to scroll. If None, scroll down/up one page
    title: Optional[str] = Field(None, description="Human readable description of what this action does")
    isExecuted: str = Field(default='pending')

class SendKeysAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    keys: str
    title: Optional[str] = Field(None, description="Human readable description of what this action does")
    isExecuted: str = Field(default='pending')

class SelectDropdownOptionAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    index: int
    text: str
    xpath: Optional[str] = None
    title: Optional[str] = Field(None, description="Human readable description of what this action does")
    isExecuted: str = Field(default='pending')
    locator: Optional[str] = None
    allUniqueLocators: Optional[list[dict]] = None

class GetDropdownOptionsAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    index: int
    xpath: Optional[str] = None
    title: Optional[str] = Field(None, description="Human readable description of what this action does")
    isExecuted: str = Field(default='pending')

class NoParamsAction(BaseModel):
    """
    Accepts absolutely anything in the incoming data
    and discards it, so the final parsed model is empty.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: Optional[str] = Field(None, description="Human readable description of what this action does")
    isExecuted: str = Field(default='pending')