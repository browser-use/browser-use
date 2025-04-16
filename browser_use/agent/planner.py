from browser_use.cache import load_cached_plan, save_plan_to_cache
import json
import re
import ast

class Planner:
    def __init__(self, llm):
        # Initialize the Planner with a language model (llm) instance
        self.llm = llm

    async def plan(self, task: str, dom_tree: str, url: str, use_cache: bool = True):
        cached = load_cached_plan(task, url, dom_tree) if use_cache else None
        if cached:
            print(" Using cached plan.")
            return cached

        print("Calling LLM to generate plan...")
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a browser automation planner. "
                    "Respond ONLY with a JSON array of actions like:\n"
                    '[{"action": "click", "selector": "#btn"}, {"action": "type", "selector": "#input", "value": "OpenAI"}]'
                )
            },
            {
                "role": "user",
                "content": f"Task: {task}\n\nDOM:\n{dom_tree[:2000]}..."  # Trim DOM if needed
            }
        ]

        response = await self.llm.ainvoke(messages)
        plan_raw = response.content.strip() if hasattr(response, "content") else str(response)

        # 🔧 Step 1: Remove "json\n" or backticks if present
        plan_raw = re.sub(r"^json\s*[\r\n]+", "", plan_raw, flags=re.IGNORECASE)
        if plan_raw.startswith("```json") or plan_raw.startswith("```"):
            lines = plan_raw.strip().splitlines()
            lines = [line for line in lines if not line.startswith("```")]
            plan_raw = "\n".join(lines).strip()

        # 🛠 Step 2: Attempt json.loads()
        try:
            plan_parsed = json.loads(plan_raw)
        except json.JSONDecodeError:
            print("JSON decode failed, attempting recovery...")
            try:
                # Replace single quotes with double quotes if possible (safe if no nesting)
                cleaned = plan_raw.replace("'", '"')
                plan_parsed = json.loads(cleaned)
                print("Recovery with double-quote replacement.")
            except json.JSONDecodeError:
                try:
                    plan_parsed = ast.literal_eval(plan_raw)
                    print("Recovery using ast.literal_eval().")
                except Exception:
                    print("Still invalid. Not caching.")
                    print("Raw response:", repr(plan_raw))
                    return plan_raw

        # Save only valid JSON
        save_plan_to_cache(task, url, dom_tree, plan_parsed)
        return plan_parsed
