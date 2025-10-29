import asyncio
import os
import sys
import logging
from datetime import datetime
from dotenv import load_dotenv
from browser_use import Agent, BrowserProfile
from browser_use.llm import ChatGoogle

# Load environment variables
load_dotenv()

# Set up API key
api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
    raise ValueError('GOOGLE_API_KEY is not set')

# Initialize LLM model
llm = ChatGoogle(model='gemini-2.5-flash', api_key=api_key)

# Set up browser profile
browser_profile = BrowserProfile(
    headless=False,
    user_data_dir='~/.config/browseruse/profiles/default',
)

logging.basicConfig(level=logging.INFO)

from browser_use.llm.messages import UserMessage, SystemMessage

async def generate_todo(task, llm_model):
    planning_prompt = f"""
Decompose the following goal into clear, actionable steps that can be completed using a web browser.

Goal: {task}

Output in markdown format with a checklist:
# To-Do List
- [ ] Step 1: ...
- [ ] Step 2: ...
Each step should be concise, web-actionable, and in logical sequence.
"""
    print("🧭 Generating plan...")

    # Wrap prompts in proper message objects
    messages = [
        SystemMessage(content="You are a precise AI task planner."),
        UserMessage(content=planning_prompt)
    ]

    try:
        plan = await llm_model.ainvoke(messages)
    except Exception as e:
        print(f"⚠️ ainvoke failed ({e}), retrying...")
        plan = await llm_model.ainvoke(messages)  # retry with same proper messages

    # Extract the actual text
    plan_text = getattr(plan, "completion", str(plan))

    with open("todo.md", "w", encoding="utf-8") as f:
        f.write(plan_text)

    print("📝 Created todo.md plan successfully.")
    return plan_text


async def execute_todo():
    if not os.path.exists("todo.md"):
        print("❌ No todo.md found. Run plan generation first.")
        return

    with open("todo.md", "r", encoding="utf-8") as f:
        lines = f.readlines()

    for idx, line in enumerate(lines):
        if line.startswith("- [ ]"):
            subtask = line.replace("- [ ]", "").strip()
            print(f"\n🚀 Executing subtask: {subtask}")

            extend_system_message = """
CRITICAL EXECUTION RULES:
1. Minimize navigation; prefer search or built-in page features.
2. Confirm visual context before acting (use vision).
3. Avoid loops or unnecessary scrolls.
4. Always verify task success before proceeding.
5. Do not perform dangerous actions like downloads or purchases unless instructed.
6. Always summarize what was achieved after execution.
"""

            agent = Agent(
                task=subtask,
                llm=llm,
                browser_profile=browser_profile,
                use_vision=True,
                headless=False,  # 👈 Force open visible browser
                max_actions_per_step=1,
                extend_system_message=extend_system_message,
                llm_timeout=90,
                max_failures=5,
            )

            try:
                result = await agent.run(max_steps=50)
                print(f"✅ Completed: {subtask}")
                print(f"🧩 Result summary: {result}")

                lines[idx] = line.replace("[ ]", "[x]")
                with open("todo.md", "w", encoding="utf-8") as f:
                    f.writelines(lines)

            except Exception as e:
                print(f"❌ Failed: {subtask} — {e}")
                continue

async def main():
    print("\n🦾 Universal Autonomous Browser Agent\n")

    task = input("💡 Enter your goal: ").strip()
    if not task:
        print("❌ Please enter a valid task description.")
        return

    plan = await generate_todo(task, llm)
    print(f"\n📋 Generated Plan:\n{plan}")

    await execute_todo()

    print("\n✅ All tasks processed! Check your todo.md for progress.\n")

if __name__ == "__main__":
    asyncio.run(main())
