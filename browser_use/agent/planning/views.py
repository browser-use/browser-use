from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any

@dataclass
class PlanningContext:
    """Context for planning operation"""
    task: str
    current_url: str
    page_title: str
    step_number: int
    recent_actions: List[str]
    has_errors: bool
    screenshot_base64: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "task": self.task,
            "current_url": self.current_url,
            "page_title": self.page_title,
            "step_number": self.step_number,
            "recent_actions": self.recent_actions,
            "has_errors": self.has_errors,
            "has_screenshot": self.screenshot_base64 is not None
        } 