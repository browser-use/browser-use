from dataclasses import dataclass
from typing import Dict, List, Optional

from browser_use.dom.views import (
    DOMState,
    DOMElementNode,
)


@dataclass(frozen=False)
class SupatestDOMElementNode(DOMElementNode):
    """
    Extended version of DOMElementNode.
    xpath: the xpath of the element from the last root node (shadow root or iframe OR document if no shadow root or iframe).
    To properly reference the element we need to recursively switch the root node until we find the element (work you way up the tree with `.parent`)
    """

    def __repr__(self) -> str:
        tag_str = f'<{self.tag_name}'

        for key, value in self.attributes.items():
            tag_str += f' {key}="{value}"'
       

        # Add extra info
        extras = []
        if self.is_interactive:
            extras.append('interactive')
        if self.is_top_element:
            extras.append('top')
        if self.shadow_root:
            extras.append('shadow-root')
        if self.highlight_index is not None:
            extras.append(f'highlight:{self.highlight_index}')

        if extras:
            tag_str += f' [{", ".join(extras)}]'

        return tag_str


@dataclass
class SupatestDOMState(DOMState):
    """Extended version of DOMState that uses SupatestDOMElementNode"""
    element_tree: SupatestDOMElementNode
    selector_map: Dict[int, SupatestDOMElementNode] 