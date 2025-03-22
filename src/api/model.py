from pydantic import BaseModel, Field
from typing import List, Any

from browser_use.browser.views import TabInfo
from browser_use.agent.views import (
    ActionResult
)


class ActionRequest(BaseModel):
    compressed_data: Any
    # dom_tree: dict
    # task: str
    # url: str
    # title: str
    # tabs: List[TabInfo]
    # chat_request_id: str


class ContextRequest(BaseModel):
    gpt_id: str = Field(
        ...,
        description="gpt id",
    ),
    user_id: str = Field(
        ...,
        description="user id"
    )


class BrowserActionNlpRequest(BaseModel):
    """
    Request model for browser action natural language processing
    """
    context: ContextRequest = Field(
        ...,
        description="Context information",
    )
    content: str = Field(
        ...,
        description="Natural language description of browser action",
        example="Click the login button on the page",
        min_length=1
    )


class BrowserActionNlpResponse(BaseModel):
    status: str = Field(
        description="action status",
        example="success",
        enum=["success", "error"]
    )
    message: str = Field(
        description="action message",
        example="start action: click button"
    )

class FileMeta(BaseModel):
    source_url: str
    file_id: str
    file_url: str
    content: str | None = None

class ChatMessage(BaseModel):
    co_instance_id: str
    content: str
    file_meta: List[dict[str, Any]] = Field(
        default=[],
        description="List of file metadata dictionaries",
        example=[
           {
                "source_url": "yyy",
                "file_id": "xxx",
                "content": "semi_struct_or_struct_data here",
                "file_url": "https://d41chssnpqdne.cloudfront.net/user_upload_by_module/xxxx",
            }
        ]
    )

class ChatResponse(BaseModel):
    content: str
    timestamp: float
    status: str


class CheckTargetPageRequest(BaseModel):
    current_page_url: str

class AgentRegisterRequest(BaseModel):
    agent_id: str

class ActionResultRequest(BaseModel):
    chat_request_id: str
    result: ActionResult

class CheckTradeActionRequest(BaseModel):
    nlp: str

class ContextCreateRequest(BaseModel):
    """
    Request model for dataframe processing

    """
    user_id: str
    file_infos: List[dict] = Field(
        default=[],
        description="List of file information objects, source_url, content, title"
    )

class Strategy(BaseModel):
    id: str | None = None
    name: str
    description: str
    content: str

class SaveStrategyRequest(BaseModel):
    strategy: Strategy

class UpdateStrategyRequest(BaseModel):
    strategy: Strategy

class RunStrategyRequest(BaseModel):
    strategy_id: str
    co_instance_id: str

class DeleteStrategyRequest(BaseModel):
    strategy_id: str
