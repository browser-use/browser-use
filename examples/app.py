import asyncio
import gradio as gr
from browser_use import Agent, BrowserSession
from browser_use.llm import ChatGoogle
from browser_use.browser import BrowserProfile
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Global Configuration ---
# Ensure your GOOGLE_API_KEY is set in your environment or a .env file
try:
    llm = ChatGoogle(model="gemini-2.5-flash", temperature=0.5)
except Exception as e:
    print(f"Error initializing the language model. Please check your API key. Details: {e}")
    llm = None

async def handle_user_task(task_input, history, session_state):
    """
    This function is the core of the chat interface. It manages the browser session,
    runs the agent with the user's task, and updates the chat history.
    """
    # Append the user's message to the chat history immediately
    history.append((task_input, None))
    yield history, session_state

    # If the LLM failed to initialize, show an error and stop.
    if llm is None:
        history.append((None, "❌ Error: Language model could not be initialized. Please check your API key and restart the application."))
        yield history, session_state
        return

    try:
        # --- 1. Manage Browser Session ---
        # If the session doesn't exist, create and start it.
        if session_state is None:
            history.append((None, "📋 No active session. Creating a new browser profile..."))
            yield history, session_state

            persistent_profile = BrowserProfile(keep_alive=True, headless=False)
            reused_session = BrowserSession(browser_profile=persistent_profile)

            history.append((None, "🚀 Starting new browser session... (A new window should appear)"))
            yield history, session_state
            
            await reused_session.start()
            session_state = reused_session  # Store the active session in the state

            history.append((None, "✅ Browser session is active. Ready for tasks."))
            yield history, session_state

        # --- 2. Execute the Agent Task ---
        history.append((None, f"🕵️ Agent starting task: '{task_input}'..."))
        yield history, session_state

        agent = Agent(
            task=task_input,
            llm=llm,
            browser_session=session_state,
        )
        agent_history = await agent.run()

        # --- 3. Report the Result ---
        if agent_history and agent_history.urls():
            final_url = agent_history.urls()[-1]
            msg = f"✅ Task complete. The browser is now on: {final_url}"
        else:
            msg = "✅ Task executed, but no new URL was navigated to."

        history.append((None, msg))
        yield history, session_state

    except Exception as e:
        error_message = f"❌ An error occurred: {e}"
        print(error_message)  # For debugging in the console
        history.append((None, error_message))
        yield history, session_state

async def end_session(history, session_state):
    """
    Cleans up and closes the browser session.
    """
    if session_state:
        history.append((None, "🧹 Closing browser session..."))
        yield history, session_state
        try:
            await session_state.kill()
            history.append((None, "✅ Session closed successfully."))
        except Exception as e:
            history.append((None, f"⚠️ Error during session cleanup: {e}"))
        finally:
            session_state = None  # Reset the state to None
            yield history, session_state
    else:
        history.append((None, "ℹ️ No active session to close."))
        yield history, session_state

# --- Gradio Interface Definition ---
with gr.Blocks(theme=gr.themes.Soft()) as demo:
    # State variables to hold the browser session and chat history across interactions
    session_state = gr.State(None)
    
    gr.Markdown("# 🤖 Browser Automation Chat")
    gr.Markdown("Type a task for the AI agent to perform in a live browser window. The session persists between tasks.")

    chatbot = gr.Chatbot(
        [],
        label="Automation Log",
        elem_id="chatbot",
        height=600,
        avatar_images=(("images/user.png"), "images/bot.png"),
        bubble_full_width=False
    )
    
    with gr.Row():
        txt = gr.Textbox(
            scale=4,
            show_label=False,
            placeholder="e.g., Go to github.com and search for 'gradio-app'",
            container=False,
        )
        submit_btn = gr.Button("▶️ Send Task", variant="primary", scale=1)

    with gr.Row():
        end_session_btn = gr.Button("⏹️ End Session & Close Browser", variant="stop")
    
    # --- Event Handlers ---

    # Handle the submission of a new task
    txt.submit(handle_user_task, [txt, chatbot, session_state], [chatbot, session_state])
    submit_btn.click(handle_user_task, [txt, chatbot, session_state], [chatbot, session_state]).then(
        lambda: gr.update(value=""), outputs=[txt] # Clear textbox after send
    )

    # Handle the "End Session" button click
    end_session_btn.click(end_session, [chatbot, session_state], [chatbot, session_state])

if __name__ == "__main__":
    demo.launch()