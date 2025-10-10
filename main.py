from dotenv import load_dotenv
import os

load_dotenv()  # loads variables from .env

api_key = os.getenv("GEMINI_API_KEY")
# Do not print API keys or other secrets. Log a non-sensitive presence check instead.
if api_key:
    print("GEMINI_API_KEY is set (value hidden)")
else:
    print("GEMINI_API_KEY is not set")
from browser_use import Agent, Browser, ChatOpenAI

# Use Browser-Use cloud browser service
browser = Browser(
    use_cloud=True,  # Automatically provisions a cloud browser
)

agent = Agent(
    task="Your task here",
    llm=ChatOpenAI(model='gpt-4.1-mini'),
    browser=browser,
)