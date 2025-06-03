import os
from dotenv import load_dotenv
from anthropic import Anthropic

# Load environment variables
load_dotenv()

# Initialize the Anthropic client
anthropic = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Try a simple completion
try:
    message = anthropic.messages.create(
        model="claude-3-opus-20240229",
        max_tokens=100,
        messages=[
            {"role": "user", "content": "Hello, Claude. Can you hear me?"}
        ]
    )
    print("API key is working!")
    print(message.content)
except Exception as e:
    print(f"Error: {e}")
