import streamlit as st
import asyncio
from browser_use import Agent, BrowserSession, Controller
from browser_use.llm import ChatGoogle
from browser_use.browser import BrowserProfile
from pydantic import BaseModel, Field
from typing import List
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# --- Configuration (Set these once) ---
st.set_page_config(layout="wide", page_title="Browser Automation Agent")

# Define the expected output structure for the LLM
class Response(BaseModel):
    sentences: List[str] = Field(description="A list of strings of response")

# Initialize the LLM and the Controller
# Make sure you have your GOOGLE_API_KEY environment variable set
try:
    llm = ChatGoogle(model="gemini-2.5-flash", temperature=0.3)
    controller = Controller(output_model=Response)
except Exception as e:
    st.error(f"Failed to initialize Google LLM. Please check your GOOGLE_API_KEY. Error: {e}")
    st.stop()


# Create a reusable browser profile.
# keep_alive=True is essential for persisting the session.
persistent_profile = BrowserProfile(
    stealth=True,
    keep_alive=True,
    headless=False,  # Set to False to see the browser in action
)

# --- Helper function to run async code in Streamlit ---
def run_async(coro):
    """
    A helper function to run an async coroutine in a synchronous environment like Streamlit.
    """
    try:
        # Check if there's a running event loop
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # If not, create a new one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# --- Streamlit UI ---

st.title("🤖 Persistent Browser Automation Agent")
st.caption("Give the agent a task, and it will control a browser to complete it. The browser stays open for follow-up commands.")

# --- Session State Initialization ---
# This is the core of persisting the browser.
if "browser_session" not in st.session_state:
    st.session_state.browser_session = None
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Sidebar for Controls ---
with st.sidebar:
    st.header("Controls")
    if st.button("⚠️ Kill Browser & Reset Session"):
        if st.session_state.browser_session:
            with st.spinner("Closing browser..."):
                run_async(st.session_state.browser_session.kill())
            st.session_state.browser_session = None
            st.session_state.messages = []  # Clear chat history
            st.success("Browser closed and session reset.")
            st.rerun()
        else:
            st.warning("No active browser session to kill.")
    st.info("The browser window will remain open between tasks. Use the kill button to close it when you're done.")


# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- Main Chat Logic ---
if prompt := st.chat_input("Give me a task for the browser..."):
    # Display user message
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        with st.spinner("Agent is thinking and working..."):
            try:
                # 1. Start the browser session IF it doesn't exist
                if st.session_state.browser_session is None:
                    st.info("🚀 Starting a new persistent browser session...")
                    # Create the session from our profile
                    session = BrowserSession(browser_profile=persistent_profile)
                    # Manually start it because keep_alive=True
                    run_async(session.start())
                    # IMPORTANT: Store the live session object in st.session_state
                    st.session_state.browser_session = session
                    st.info("✅ Browser session is live and will be reused for future tasks.")

                # 2. Create an Agent for the current task, passing the EXISTING session
                agent = Agent(
                    task=prompt,
                    llm=llm,
                    controller=controller,
                    # This is the key to reusing the browser!
                    browser_session=st.session_state.browser_session,
                    logging=True
                )

                # 3. Run the agent's task
                history = run_async(agent.run())
                response_text = history.final_result()

                # 4. Display the result
                st.markdown(response_text)
                # Also show the final URL for context
                if history.urls():
                    st.info(f"Final URL: {history.urls()[-1]}")

                # Add assistant response to chat history
                st.session_state.messages.append({"role": "assistant", "content": response_text})

            except Exception as e:
                st.error(f"An error occurred: {e}")
                # Optional: kill the session on a critical error
                if st.session_state.browser_session:
                    run_async(st.session_state.browser_session.kill())
                    st.session_state.browser_session = None
                st.warning("A critical error occurred. The browser session has been terminated.")