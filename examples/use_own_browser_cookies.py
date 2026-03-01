"""
Example: Authenticated Agent using Local Browser Cookies

This example demonstrates how to inject an existing authenticated session 
(cookies) from your local Chrome browser into Browser Use. 

This is useful for bypassing:
- 2FA / MFA prompts
- CAPTCHAs
- "Suspicious Activity" blocks
- Login screens

Prerequisites:
    pip install romek
    romek grab x.com  # Run this in terminal first
"""

import json
import os
import tempfile
from langchain_openai import ChatOpenAI
from browser_use import Agent, Browser, BrowserConfig

# Optional: Import Romek to get fresh cookies dynamically
try:
    from romek import Vault
    HAS_ROMEK = True
except ImportError:
    HAS_ROMEK = False
    print("Romek not installed. Run `pip install romek` to fetch local cookies.")


def run_authenticated_agent():
    # 1. Get cookies from local Chrome (using Romek)
    cookies = []
    if HAS_ROMEK:
        print("🔓 Fetching local cookies for x.com...")
      vault = Vault()
        cookies = vault.get_session("x.com")
    
    # 2. Create a Playwright-compatible storage state in a temp file
    auth_state = {
        "cookies": cookies, 
        "origins": []
    }
    
    # Use temp file to avoid leaving credentials on disk
    auth_fd, auth_file = tempfile.mkstemp(suffix=".json", prefix="romek_auth_")
    
    try:
        with os.fdopen(auth_fd, "w") as f:
            json.dump(auth_state, f)

        # 3. Initialize Browser with the authenticated state
        browser = Browser(
            config=BrowserConfig(
                storage_state=auth_file,
            )
        )

        # 4. Run the Agent (starts already logged in)
        agent = Agent(
            task="Go to x.com and tell me the top trending topic",
            llm=ChatOpenAI(model="gpt-4o"),
            browser=browser,
        )

        import asyncio
        asyncio.run(agent.run())
    
    finally:
        # Always cleanup, even on error
        if os.path.exists(auth_file):
            os.remove(auth_file)


if __name__ == "__main__":
    run_authenticated_agent()
