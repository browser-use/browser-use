from dataclasses import dataclass, field
from typing import Dict, Optional

from browser_use.browser.views import (
    BrowserState,
    TabInfo,
    URLNotAllowedError,
)
from supatest.dom.views import SupatestDOMElementNode


@dataclass
class SupatestBrowserState(BrowserState):
    """Extended version of BrowserState that uses SupatestDOMElementNode"""
    url: str = ""
    title: str = ""
    scroll_x: int = 0
    scroll_y: int = 0
    element_tree: Optional[SupatestDOMElementNode] = None
    selector_map: Dict[int, SupatestDOMElementNode] = field(default_factory=dict)
    tabs: list[TabInfo] = field(default_factory=list)

    def __post_init__(self):
        self.selector_map = self.selector_map or {}
        self.tabs = self.tabs or [] 