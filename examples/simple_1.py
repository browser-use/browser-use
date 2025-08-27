import asyncio
from browser_use import Agent, BrowserSession
from browser_use.llm import ChatGoogle
from browser_use.browser import BrowserProfile
import os
from dotenv import load_dotenv
load_dotenv()

# Make sure you have your OPENAI_API_KEY environment variable set
llm = ChatGoogle(model="gemini-2.5-flash", temperature=0.5)


async def main():
    # 1. Create a BrowserProfile to hold the reusable configuration.
    #    The key is setting `keep_alive=True` here.
    print("📋 Creating a reusable browser profile with keep_alive=True...")
    persistent_profile = BrowserProfile(
        keep_alive=True,      # This is crucial! Prevents the browser from closing.
        headless=False,       # You can set other default configs here too.
    )

    # 2. Create a single BrowserSession using the profile.
    #    It will inherit the `keep_alive` setting.
    print("🚀 Starting a reusable browser session from the profile...")
    reused_session = BrowserSession(
        browser_profile=persistent_profile
    )

    # 3. When keep_alive=True, you must start the session manually.
    await reused_session.start()

    # --- Task 1: Search on Google ---
    print("\n🕵️ Starting Agent 1: Searching for 'Browser-Use library'")
    agent1 = Agent(
        task="Go to google.com, search for 'Browser-Use library' and click on the first link",
        llm=llm,
        browser_session=reused_session,  # Pass the existing session
    )
    history1 = await agent1.run()
    print("✅ Agent 1 finished. Browser is now on the search results page.")
    # Check if any URLs were visited before accessing the last one
    if history1.urls():
        print(f"Final URL from Agent 1: {history1.urls()[-1]}")
    else:
        print("Agent 1 did not navigate to any new URLs.")


    # --- Task 2: Click the GitHub link from the previous context ---
    print("\n🕵️ Starting Agent 2: Clicking the GitHub link from results page")
    # The browser context (page, cookies) is automatically maintained.
    # We just give the new agent a new task.
    agent2 = Agent(
        task="from current page go to documentation of browser-use",
        llm=llm,
        browser_session=reused_session,  # Pass the SAME session object
    )
    history2 = await agent2.run()
    print("✅ Agent 2 finished. Browser should now be on the GitHub page.")
    if history2.urls():
        print(f"Final URL from Agent 2: {history2.urls()[-1]}")
    else:
        print("Agent 2 did not navigate to any new URLs.")


    # --- Cleanup: Close the session ---
    print("\n teardown All tasks complete. Closing the browser session.")
    await reused_session.kill()

if __name__ == "__main__":
    asyncio.run(main())