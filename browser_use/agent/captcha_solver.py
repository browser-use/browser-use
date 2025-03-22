from __future__ import annotations
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from browser_use.agent.service import Agent

class CaptchaSolverProtocol(Protocol):
    async def solve_captcha(self, context: Agent) -> None:
        ...
