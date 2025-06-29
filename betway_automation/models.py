from pydantic import BaseModel, Field
from typing import Optional


class LoginAction(BaseModel):
    """Pydantic model for the login action."""

    username: str = Field(..., description="Mobile number or username for login")
    password: str = Field(..., description="Password for login")


class MarketAction(BaseModel):
    """Pydantic model for market visibility action."""

    market_name: str = Field(
        ..., description="The exact name of the betting market to make visible"
    )


class BetAction(BaseModel):
    """Pydantic model for placing a bet."""

    team_or_outcome: str = Field(
        ...,
        description="The team name or outcome to bet on (e.g., 'PSG', 'No', 'Chelsea')",
    )
    market_type: str = Field(
        ..., description="The market type (e.g., '1x2', 'Both Teams To Score')"
    )
    match_description: Optional[str] = Field(
        None, description="Optional match description for context"
    )
