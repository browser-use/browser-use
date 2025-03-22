from typing import Optional
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from browser_use.agent.prompts import SystemPrompt

class IsTargetPage(BaseModel):
    result: bool

class CheckTradeAction(BaseModel):
    is_trade_action: bool
    action: str
    coin_name: str
    amount: float
    unit: str

class ActionAgentConfig(BaseModel):
    task: str
    llm: Optional[ChatOpenAI]

class GetContentByImage(BaseModel):
    table_list: list[dict]


class MySystemPrompt(SystemPrompt):
    def important_rules(self) -> str:
        # Get existing rules from parent class
        existing_rules = super().important_rules()

        # Add your custom rules
        new_rules = """
9. MOST IMPORTANT RULE:
- You know very clearly how to operate cryptocurrency trading
- the web url of gmgn is https://gmgn.ai
"""

        # Make sure to use this pattern otherwise the exiting rules will be lost
        return f'{existing_rules}\n{new_rules}'