import os
from langchain.agents import Agent

# Create the agent with our custom controller

# Use absolute path for conversation saving
conversation_path = os.path.join(os.getcwd(), "betway_login_conversation.json")
print(f"💾 Will save conversation to: {conversation_path}")

agent = Agent(
    task=f"Go to Betway.co.za and log in using the username '{username}' and password '{password}'. Use the login_user action to log in.",
    llm=llm,
    controller=betway_controller,
    use_vision=True,  # Enable screenshot analysis
    save_conversation_path=conversation_path,
)
