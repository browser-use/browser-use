import logging
import gc

from typing import List, Optional, Any
from dataclasses import dataclass

from browser_use.browser.views import BrowserState, TabInfo
from browser_use.agent.message_manager.service import MessageManager, MessageManagerSettings
from browser_use.agent.service import log_response
from browser_use.agent.views import (
    AgentOutput, ActionResult, AgentSettings, AgentState,
)
from browser_use.agent.prompts import SystemPrompt
from src.controller.service import Controller
from browser_use.dom.history_tree_processor.view import Coordinates
from browser_use.dom.views import (
	CoordinateSet,
	DOMBaseNode,
	DOMElementNode,
	DOMTextNode,
	SelectorMap,
)

@dataclass
class ViewportInfo:
	width: int
	height: int

logger = logging.getLogger(__name__)


class ActionAgentService:
    def __init__(self, task, llm, controller=Controller(), override_system_message = None, extend_system_message = None, sensitive_data = None):
        self.llm = llm
        self.task = task
        self.controller = controller
        self.settings = AgentSettings()
        self.available_actions = self.controller.registry.get_prompt_description()
        self.state = AgentState()
        # 初始化可能需要的配置
        self.message_manager = MessageManager(
            task=task,
            system_message=SystemPrompt(
                action_description=self.available_actions,
                max_actions_per_step=self.settings.max_actions_per_step,
                override_system_message=override_system_message,
                extend_system_message=extend_system_message,
            ).get_system_message(),
            settings=MessageManagerSettings(
                max_input_tokens=self.settings.max_input_tokens,
                include_attributes=self.settings.include_attributes,
                message_context=self.settings.message_context,
                sensitive_data=sensitive_data,
                available_file_paths=self.settings.available_file_paths,
            ),
            state=self.state.message_manager_state,
        )
        self.tool_calling_method = 'function_calling'
        self._setup_action_models()
        self.current_state = Optional[BrowserState]
        self.latest_result: Optional[List[ActionResult]] = None

    def _setup_action_models(self) -> None:
        """Setup dynamic action models from controller's registry"""
        # Get the dynamic action model from controller's registry
        self.ActionModel = self.controller.registry.create_action_model()
        # Create output model with the dynamic actions
        self.AgentOutput = AgentOutput.type_with_custom_actions(self.ActionModel)

    async def _construct_dom_tree(
            self,
            eval_page: dict,
    ) -> tuple[DOMElementNode, SelectorMap]:
        js_node_map = eval_page['map']
        js_root_id = eval_page['rootId']

        selector_map = {}
        node_map = {}

        for id, node_data in js_node_map.items():
            node, children_ids = self._parse_node(node_data)
            if node is None:
                continue

            node_map[id] = node

            if isinstance(node, DOMElementNode) and node.highlight_index is not None:
                selector_map[node.highlight_index] = node

            # NOTE: We know that we are building the tree bottom up
            #       and all children are already processed.
            if isinstance(node, DOMElementNode):
                for child_id in children_ids:
                    if child_id not in node_map:
                        continue

                    child_node = node_map[child_id]

                    child_node.parent = node
                    node.children.append(child_node)

        html_to_dict = node_map[str(js_root_id)]

        del node_map
        del js_node_map
        del js_root_id

        gc.collect()

        if html_to_dict is None or not isinstance(html_to_dict, DOMElementNode):
            raise ValueError('Failed to parse HTML to dictionary')

        return html_to_dict, selector_map

    def get_selector_map_serializable(self) -> dict[str, Any]:
        serializable_selector_map = {}
        for idx, node in self.current_state.selector_map.items():
            serializable_selector_map[idx] = {
                "tag_name": node.tag_name,
                "xpath": node.xpath,
                "attributes": node.attributes,
                "is_interactive": node.is_interactive,
                "is_visible": node.is_visible,
                "is_top_element": node.is_top_element,
                "is_in_viewport": node.is_in_viewport,
                "highlight_index": node.highlight_index,
                "viewport_coordinates": node.viewport_coordinates.model_dump() if node.viewport_coordinates else None,
                "page_coordinates": node.page_coordinates.model_dump() if node.page_coordinates else None,
                "viewport_info": {"width": node.viewport_info.width,
                                  "height": node.viewport_info.height} if node.viewport_info else None
            }
        return serializable_selector_map

    def _parse_node(
            self,
            node_data: dict,
    ) -> tuple[Optional[DOMBaseNode], list[int]]:
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

        # Process coordinates if they exist for element nodes

        viewport_info = None

        if 'viewport' in node_data:
            viewport_info = ViewportInfo(
                width=node_data['viewport']['width'],
                height=node_data['viewport']['height'],
            )

        element_node = DOMElementNode(
            tag_name=node_data['tagName'],
            xpath=node_data['xpath'],
            attributes=node_data.get('attributes', {}),
            children=[],
            is_visible=node_data.get('isVisible', False),
            is_interactive=node_data.get('isInteractive', False),
            is_top_element=node_data.get('isTopElement', False),
            is_in_viewport=node_data.get('isInViewport', False),
            highlight_index=node_data.get('highlightIndex'),
            shadow_root=node_data.get('shadowRoot', False),
            parent=None,
            viewport_info=viewport_info,
        )

        children_ids = node_data.get('children', [])

        return element_node, children_ids

    async def _set_current_state(self, dom_tree: dict, url: str, title: str, tabs: List[TabInfo]):
        element_tree, selector_map = await self._construct_dom_tree(dom_tree)

        self.current_state = BrowserState(
            element_tree=element_tree,
            selector_map=selector_map,
            url=url,
            title=title,
            tabs=tabs
        )

    async def get_next_actions(self, dom_tree: dict, url: str, title: str, tabs: List[TabInfo]):
        await self._set_current_state(dom_tree, url, title, tabs)

        self.message_manager.add_state_message(self.current_state, self.latest_result)

        input_messages = self.message_manager.get_messages()

        structured_llm = self.llm.with_structured_output(self.AgentOutput, include_raw=True,
                                                         method=self.tool_calling_method)
        response: dict[str, Any] = await structured_llm.ainvoke(input_messages)  # type: ignore
        parsed: AgentOutput | None = response['parsed']
        logger.info(f"Received parsed data: {parsed}")
        log_response(parsed)
        return response

    async def set_action_result(self, result: ActionResult):
        self.latest_result = [result]
        return self.latest_result
