from dotenv import load_dotenv
import os
from browser_use import Agent, ChatGoogle

# Load environment variables from project root
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=env_path)

api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise RuntimeError("GOOGLE_API_KEY not found in .env!")

print("GOOGLE_API_KEY loaded:", True)

# Explicit task for agent
task_description = """
Open the GitHub page for the browser-use repository: 
https://github.com/browser-use/browser-use
Find the number of stars displayed on the top right of the repo page.
Return only the numeric count as an integer.
"""

agent = Agent(
    task=task_description,
    llm=ChatGoogle(model="gemini-2.5-flash"),
)

try:
    result = agent.run_sync()
    print("GitHub browser-use stars:", result)
except Exception as e:
    print("Agent failed with error:", e)

# Keep the browser open for observation
import time
time.sleep(30)
