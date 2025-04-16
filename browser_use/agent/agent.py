from playwright.async_api import async_playwright, Page
import json
import os
from browser_use.agent.planner import Planner

class Agent:
    def __init__(self, task, llm, start_url=None):
        """
        Initialize the Agent with a task, language model, and optional start URL.
        - task: The task to be performed by the agent.
        - llm: The language model used for planning.
        - start_url: The initial URL to navigate to (default: Google).
        """
        self.task = task
        self.llm = llm
        self.start_url = start_url or "https://www.google.com"
        self.planner = Planner(llm)  # Initialize the planner with the language model.

    async def run(self):
        """
        Main method to:
        1. Launch the browser.
        2. Inject a DOM extraction script.
        3. Generate a plan using the planner.
        4. Execute the generated plan.
        """
        async with async_playwright() as p:
            # Launch Chromium browser in non-headless mode for visibility.
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(self.start_url)  # Navigate to the start URL.

            dom_tree = await page.content()
            url = page.url  # Get the current page URL.
            # Generate a plan using the planner based on the task, DOM tree, and URL.
            plan = await self.planner.plan(self.task, dom_tree, url, use_cache=True)
            # Execute the generated plan.
            await self.execute_plan(plan, page)

            # Return a message for the UI
            return "Task executed using cached or generated plan."

    async def execute_plan(self, plan, page: Page):
        """
        Execute a sequence of actions (plan) on the given page.
        Supported actions:
        - click: Click on an element.
        - type: Type text into an input field.
        - wait_for: Wait for an element to appear.
        - screenshot: Take a screenshot of the page.
        - extract_text: Extract text from an element.
        """
        try:
            if isinstance(plan, str):
                try:
                    plan = json.loads(plan)
                except json.JSONDecodeError:
                    print("LLM response is not valid JSON.")
                    print("Raw plan:", repr(plan))
                    return

            for step in plan:
                action = step.get("action")
                selector = step.get("selector")

                if not selector:
                    print(f"Missing selector for action: {action}")
                    continue

                if action == "click":
                    try:
                        print(f"Waiting then clicking: {selector}")
                        await page.wait_for_selector(selector, timeout=10000, state="visible")
                        await page.click(selector)
                    except Exception as e:
                        print(f"Click failed: {e}")

                elif action == "type":
                    value = step.get("value", "")
                    try:
                        print(f"Waiting then typing '{value}' into {selector}")
                        await page.wait_for_selector(selector, timeout=10000, state="visible")
                        await page.fill(selector, value)
                    except Exception as e:
                        print(f"Typing failed: {e}")

                elif action == "wait_for":
                    try:
                        print(f"Waiting for {selector}")
                        await page.wait_for_selector(selector, timeout=15000, state="visible")
                    except Exception as e:
                        print(f"Wait failed: {e}")

                elif action == "screenshot":
                    path = step.get("path", "screenshot.png")
                    print(f"Taking screenshot to {path}")
                    await page.screenshot(path=path)

                elif action == "extract_text":
                    try:
                        element = await page.query_selector(selector)
                        text = await element.inner_text() if element else ""
                        print(f"Extracted text: {text}")
                    except Exception as e:
                        print(f"Text extraction failed: {e}")

                else:
                    print(f"Unknown action: {action}")

        except Exception as e:
            print(f"Fatal error while executing plan: {e}")
