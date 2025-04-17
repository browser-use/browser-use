from playwright.async_api import async_playwright, Page
import json
import logging
import base64
from typing import List, Union, Dict, Any
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from browser_use.agent.planner import Planner

class Agent:
    def __init__(self, task, llm, start_url=None):
        """
        Initialize the Agent with a task, language model, and optional start URL.
        - task: The task to be performed by the agent.
        - llm: The language model used for planning.
        - start_url: The initial URL to navigate to (default: Google).
        """
        self.task = task.replace("seaech", "search")
        self.llm = llm
        self.start_url = start_url or "https://www.google.com"
        self.planner = Planner(llm)
        self.logger = logging.getLogger(__name__)

    def sanitize_message_content(self, msg: BaseMessage) -> BaseMessage:
        """
        Ensures message content is a plain string or properly typed blocks.
        Fixes invalid blocks like [{}] or [{'text': 'hi'}] -> [{'type': 'text', 'text': 'hi'}].
        """
        content = msg.content
        if isinstance(content, str):
            return msg
        elif isinstance(content, list):
            sanitized = []
            for item in content:
                if isinstance(item, str):
                    sanitized.append({"type": "text", "text": item})
                elif isinstance(item, dict):
                    if "type" in item and item["type"] in ["text", "image_url"]:
                        sanitized.append(item)
                    else:
                        self.logger.warning(f"Unexpected dictionary structure: {item}")
                        if "text" in item:
                            sanitized.append({"type": "text", "text": str(item["text"])})
                        elif "image_url" in item and isinstance(item["image_url"], dict) and "url" in item["image_url"]:
                            sanitized.append({"type": "image_url", "image_url": item["image_url"]})
                        else:
                            sanitized.append({"type": "text", "text": str(item)})
                else:
                    self.logger.warning(f"Unexpected item type: type={type(item)}, value={item}")
                    sanitized.append({"type": "text", "text": str(item)})
            if not sanitized:
                self.logger.warning(f"No valid content blocks: {content}")
                return HumanMessage(content="") if isinstance(msg, HumanMessage) else msg
            return HumanMessage(content=sanitized) if isinstance(msg, HumanMessage) else msg
        else:
            self.logger.warning(f"Unexpected content type: type={type(content)}, value={content}")
            return HumanMessage(content=str(content)) if isinstance(msg, HumanMessage) else msg

    async def run(self):
        """
        Main method to:
        1. Launch the browser.
        2. Inject a DOM extraction script.
        3. Generate a plan using the planner.
        4. Execute the generated plan.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(self.start_url)

            dom_tree = await page.content()
            url = page.url
            # Capture screenshot for vision support
            screenshot = await page.screenshot(full_page=True, type="png")
            screenshot_base64 = base64.b64encode(screenshot).decode()
            # Construct messages for the planner
            messages = [
                SystemMessage(content=(
                    "You are a browser automation planner. "
                    "Respond ONLY with a JSON array of actions like:\n"
                    '[{"action": "click", "selector": "#btn"}, {"action": "type", "selector": "#input", "value": "OpenAI"}]'
                )),
                HumanMessage(content=[
                    {"type": "text", "text": f"Task: {self.task}\nCurrent URL: {url}\nDOM Tree: {dom_tree[:1000]}..."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"}}
                ])
            ]
            # Sanitize messages
            sanitized_messages = [self.sanitize_message_content(msg) for msg in messages]
            for i, msg in enumerate(sanitized_messages):
                self.logger.debug(f"Message {i}: type={type(msg.content)}, content={msg.content}")
            # Generate a plan using sanitized messages
            try:
                plan = await self.planner.plan(self.task, url, dom_tree, sanitized_messages, use_cache=True)
                if isinstance(plan, str):
                    self.logger.error(f"Invalid plan format received: {plan}")
                    return "Task failed: Invalid plan format"
                await self.execute_plan(plan, page)
            except Exception as e:
                self.logger.error(f"Failed to generate or execute plan: {e}")
                return f"Task failed: {e}"

            return "Task executed using cached or generated plan."

    async def execute_plan(self, plan: List[Dict[str, Any]], page: Page) -> None:
        """
        Execute high-level semantic plan actions.
        """
        try:
            if not plan:
                self.logger.error("No plan provided")
                return

            for step in plan:
                if not isinstance(step, dict) or len(step) != 1:
                    self.logger.error(f"Invalid step format: {step}")
                    continue

                action_name, params = next(iter(step.items()))

                if action_name == "search_google":
                    query = params.get("query")
                    if not query:
                        self.logger.error("Missing query for search_google")
                        continue
                    self.logger.info(f"Searching for: {query}")
                    await page.evaluate(
                        """(query) => {
                            window.dispatchEvent(new CustomEvent("agent-action", {
                                detail: {
                                    type: "search_google",
                                    query: query
                                }
                            }));
                        }""",
                        query
                    )

                elif action_name == "click_element_by_index":
                    index = params.get("index")
                    if index is None:
                        self.logger.error("Missing index for click_element_by_index")
                        continue
                    self.logger.info(f"Clicking element by index: {index}")
                    await page.evaluate(
                        """(index) => {
                            window.dispatchEvent(new CustomEvent("agent-action", {
                                detail: {
                                    type: "click_element_by_index",
                                    index: index
                                }
                            }));
                        }""",
                        index
                    )

                elif action_name == "done":
                    self.logger.info(f"Task completed: {params.get('text', '')}")
                    break

                else:
                    self.logger.warning(f"Unknown action: {action_name}")

        except Exception as e:
            self.logger.error(f"Error executing plan: {e}")