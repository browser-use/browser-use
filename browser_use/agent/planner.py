from browser_use.cache import load_cached_plan, save_plan_to_cache
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from typing import List, Union,Dict, Any
import json
import re
import ast
import logging

logger = logging.getLogger(__name__)

class Planner:
    def __init__(self, llm):
        self.llm = llm
        self.system_message = SystemMessage(content="""You are a browser automation planner. Your task is to generate a sequence of actions to complete a given task.
The output must be a JSON array of actions, where each action has the following format:
{
    "action": "action_type",
    "params": {
        "param1": "value1",
        "param2": "value2"
    }
}

Valid action types:
- navigate: Requires "url" parameter
- type: Requires "text" parameter and optionally "index" parameter
- click: Requires "index" parameter
- press_enter: Requires "index" parameter
- done: No parameters required

The first action must always be a "navigate" action.
""")

    async def plan(self, task: str, url: str, dom: str, messages: List[BaseMessage], use_cache: bool = True) -> List[Dict[str, Any]]:
        """
        Generate a plan for the given task using the provided messages.
        - task: The task to plan for.
        - url: Current page URL.
        - dom: DOM tree content.
        - messages: List of BaseMessage objects.
        - use_cache: Whether to use cached plans.
        """
        # Check cache first
        if use_cache:
            cached = load_cached_plan(task, url, dom)
            if cached:
                logger.info("Using cached plan.")
                return cached

        logger.info("Calling LLM to generate plan...")
        try:
            # Add system message to the beginning of messages
            plan_messages = [self.system_message] + messages
            response = await self.llm.ainvoke(plan_messages)
            plan_raw = response.content.strip() if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.error(f"LLM invocation failed: {e}")
            return []

        # Clean up response
        plan_raw = re.sub(r"^json\s*[\r\n]+", "", plan_raw, flags=re.IGNORECASE)
        if plan_raw.startswith("```json") or plan_raw.startswith("```"):
            lines = plan_raw.strip().splitlines()
            lines = [line for line in lines if not line.startswith("```")]
            plan_raw = "\n".join(lines).strip()

        # Parse response
        try:
            plan_parsed = json.loads(plan_raw)
        except json.JSONDecodeError:
            logger.info("JSON decode failed, attempting recovery...")
            try:
                cleaned = plan_raw.replace("'", '"')
                plan_parsed = json.loads(cleaned)
                logger.info("Recovery with double-quote replacement.")
            except json.JSONDecodeError:
                try:
                    plan_parsed = ast.literal_eval(plan_raw)
                    logger.info("Recovery using ast.literal_eval().")
                except Exception:
                    logger.error(f"Invalid plan format. Raw response: {repr(plan_raw)}")
                    return []

        # Handle dictionary response with 'action' field
        if isinstance(plan_parsed, dict) and "action" in plan_parsed:
            logger.info("Extracting 'action' field from dictionary response")
            plan_parsed = plan_parsed["action"]

        # Validate plan format
        if not isinstance(plan_parsed, list):
            logger.error(f"Invalid plan format, expected list: {plan_parsed}")
            return []

        # Validate and map actions
        valid_actions = []
        for i, action in enumerate(plan_parsed):
            if not isinstance(action, dict):
                logger.warning(f"Invalid action format: {action}")
                continue
            if "action" not in action or "params" not in action:
                logger.warning(f"Action missing required fields: {action}")
                continue
            if not isinstance(action["params"], dict):
                logger.warning(f"Invalid params format: {action['params']}")
                continue

            # Map unsupported actions
            action_type = action["action"]
            if action_type == "input_text":
                action_type = "type"
                action["action"] = "type"
                if "text" not in action["params"]:
                    action["params"]["text"] = action["params"].get("value", "")
                if "selector" not in action["params"]:
                    action["params"]["selector"] = f"input:nth-child({action['params'].get('index', 1)})"
            elif action_type == "press_enter":
                action_type = "type"
                action["action"] = "type"
                action["params"] = {"selector": "input:focus", "text": "\n"}

            # Validate action types
            if action_type not in ["navigate", "type", "click", "done"]:
                logger.warning(f"Invalid action type: {action_type}")
                continue

            # Validate first action
            if i == 0 and action_type != "navigate":
                logger.warning("First action must be 'navigate'")
                continue

            # Validate required params
            if action_type == "navigate" and "url" not in action["params"]:
                logger.warning("Navigate action missing 'url' parameter")
                continue
            elif action_type == "type" and ("selector" not in action["params"] or "text" not in action["params"]):
                logger.warning("Type action missing 'selector' or 'text' parameter")
                continue
            elif action_type == "click" and "selector" not in action["params"]:
                logger.warning("Click action missing 'selector' parameter")
                continue
            elif action_type == "done" and "success" not in action["params"]:
                logger.warning("Done action missing 'success' parameter")
                continue

            valid_actions.append(action)

        if not valid_actions:
            logger.warning("No valid actions found in plan")
            return []

        # Save valid plan to cache
        save_plan_to_cache(task, url, dom, valid_actions)
        return valid_actions