import gc
import json
import logging
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING, Optional, Tuple, Dict, cast

if TYPE_CHECKING:
    from playwright.async_api import Page

from browser_use.dom.service import DomService, ViewportInfo
from browser_use.dom.views import DOMBaseNode, DOMTextNode, CoordinateSet, DOMElementNode
from browser_use.utils import time_execution_async

from supatest.dom.views import SupatestDOMElementNode, SupatestDOMState

logger = logging.getLogger(__name__)


class SupatestDomService(DomService):
    def __init__(self, page: 'Page'):
        super().__init__(page)
        # Use the original buildDomTree.js from browser_use
        self.js_code = resources.read_text('browser_use.dom', 'buildDomTree.js')

    @time_execution_async('--get_clickable_elements')
    async def get_clickable_elements(
        self,
        highlight_elements: bool = True,
        focus_element: int = -1,
        viewport_expansion: int = 0,
    ) -> SupatestDOMState:
        logger.debug("[Supatest] Getting clickable elements")
        element_tree, selector_map = await self._build_dom_tree(highlight_elements, focus_element, viewport_expansion)
        # Cast the types to match SupatestDOMState requirements
        supatest_tree = cast(SupatestDOMElementNode, element_tree)
        supatest_map = cast(Dict[int, SupatestDOMElementNode], selector_map)
        logger.debug(f"[Supatest] Found {len(supatest_map)} clickable elements")
        return SupatestDOMState(element_tree=supatest_tree, selector_map=supatest_map)

    @time_execution_async('--build_dom_tree')
    async def _build_dom_tree(
        self,
        highlight_elements: bool,
        focus_element: int,
        viewport_expansion: int,
    ) -> Tuple[SupatestDOMElementNode, Dict[int, SupatestDOMElementNode]]:
        logger.debug("[Supatest] Starting DOM tree build")
        
        if await self.page.evaluate('1+1') != 2:
            raise ValueError('The page cannot evaluate javascript code properly')

        debug_mode = logger.getEffectiveLevel() == logging.DEBUG
        args = {
            'doHighlightElements': highlight_elements,
            'focusHighlightIndex': focus_element,
            'viewportExpansion': viewport_expansion,
            'debugMode': debug_mode,
        }

        try:
            logger.debug("[Supatest] Evaluating custom buildDomTree.js")
            eval_page = await self.page.evaluate(self.js_code, args)
            logger.debug("[Supatest] Successfully evaluated buildDomTree.js")
        except Exception as e:
            logger.error('Error evaluating JavaScript: %s', e)
            raise

        if debug_mode and 'perfMetrics' in eval_page:
            logger.debug('DOM Tree Building Performance Metrics:\n%s', json.dumps(eval_page['perfMetrics'], indent=2))

        return await self._construct_dom_tree(eval_page)

    @time_execution_async('--construct_dom_tree')
    async def _construct_dom_tree(
        self,
        eval_page: dict,
    ) -> Tuple[SupatestDOMElementNode, Dict[int, SupatestDOMElementNode]]:
        logger.debug("[Supatest] Constructing DOM tree")
        js_node_map = eval_page['map']
        js_root_id = eval_page['rootId']

        selector_map: Dict[int, SupatestDOMElementNode] = {}
        node_map = {}

        for id, node_data in js_node_map.items():
            node, children_ids = self._parse_node(node_data)
            if node is None:
                continue

            node_map[id] = node

            if isinstance(node, SupatestDOMElementNode) and node.highlight_index is not None:
                selector_map[node.highlight_index] = node

            # Build the tree bottom up
            if isinstance(node, SupatestDOMElementNode):
                for child_id in children_ids:
                    if child_id not in node_map:
                        continue

                    child_node = node_map[child_id]
                    child_node.parent = node
                    node.children.append(child_node)

        root_node = node_map[str(js_root_id)]

        del node_map
        del js_node_map
        del js_root_id

        gc.collect()

        if root_node is None or not isinstance(root_node, SupatestDOMElementNode):
            raise ValueError('Failed to parse HTML to dictionary')

        logger.debug(f"[Supatest] DOM tree construction complete, root node: {root_node}")
        return root_node, selector_map

    def _parse_node(
        self,
        node_data: dict,
    ) -> Tuple[Optional[DOMBaseNode], list[int]]:
        if not node_data:
            return None, []

        # Process text nodes immediately
        if node_data.get('type') == 'TEXT_NODE':
            text_node = DOMTextNode(
                text=node_data['text'],
                is_visible=node_data['isVisible'],
                parent=None,
            )
            return text_node, []

        logger.debug(f"[Supatest] Processing node data: {json.dumps(node_data, indent=2)}")

        # Process coordinates if they exist
        viewport_coordinates = None
        page_coordinates = None
        viewport_info = None

        if 'viewport' in node_data:
            viewport_info = ViewportInfo(
                width=node_data['viewport']['width'],
                height=node_data['viewport']['height'],
            )

        if 'coordinates' in node_data:
            coords = node_data['coordinates']
            if 'viewport' in coords:
                v = coords['viewport']
                viewport_coordinates = CoordinateSet(
                    x=v['x'],
                    y=v['y'],
                    width=v['width'],
                    height=v['height'],
                )
            if 'page' in coords:
                p = coords['page']
                page_coordinates = CoordinateSet(
                    x=p['x'],
                    y=p['y'],
                    width=p['width'],
                    height=p['height'],
                )

        # Create SupatestDOMElementNode instead of DOMElementNode
        element_node = SupatestDOMElementNode(
            tag_name=node_data['tagName'],
            xpath=node_data['xpath'],
            attributes=node_data.get('attributes', {}),
            children=[],
            is_visible=node_data.get('isVisible', False),
            is_interactive=node_data.get('isInteractive', False),
            is_top_element=node_data.get('isTopElement', False),
            highlight_index=node_data.get('highlightIndex'),
            shadow_root=node_data.get('shadowRoot', False),
            parent=None,
            viewport_coordinates=viewport_coordinates,
            page_coordinates=page_coordinates,
            viewport_info=viewport_info,
        )

        children_ids = node_data.get('children', [])

        return element_node, children_ids 