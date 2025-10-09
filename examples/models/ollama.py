# 1. Install Ollama: https://github.com/ollama/ollama
# 2. Run `ollama serve` to start the server
# 3. In a new terminal, install the model you want to use: `ollama pull llama3.1:8b` (this has 4.9GB)

# Fix 1: Only import Agent and ChatOllama once
from browser_use import Agent, ChatOllama

# Fix 2: Import os to handle environment variables for robust host setting
import os

# --- Basic Example (Assuming default local Ollama setup) ---

# Set the OLLAMA_HOST environment variable to ensure the client connects correctly
# This addresses the original timeout/port issue by forcing the default host.
os.environ.setdefault('OLLAMA_HOST', 'http://127.0.0.1:11434')

llm = ChatOllama(model='llama3.1:8b')

# Fix 3: Assign the Agent instance to a variable 'agent'
agent = Agent('find the founders of browser-use', llm=llm)

print("Starting basic agent with Ollama...")
# Fix 4: Correctly call run_sync() on the 'agent' instance
result = agent.run_sync() 
print(f"\nResult: {result}")


# --- Example with Custom Configuration ---

def custom_example():
    """Example with custom Ollama configuration."""
    
    # Fix 5: Removed unsupported parameters (temperature, num_predict) 
    # from the ChatOllama constructor, as they caused Pylance errors.
    # The 'host' and 'timeout' are typically supported for connection config.
    llm_custom = ChatOllama(
        model='llama3.1:8b',
        # NOTE: Using a remote IP (192.168.1.100) requires Ollama to be 
        # configured to bind to that interface, e.g., via OLLAMA_HOST='0.0.0.0'.
        host='http://192.168.1.100:11434',
        timeout=300,  # Longer timeout for slower systems
    )
    
    agent_custom = Agent(
        task='Search for Python tutorials',
        llm=llm_custom
    )
    
    print("\nStarting custom agent with Ollama...")
    return agent_custom.run_sync()


if __name__ == '__main__':
    # You can call the custom example here if needed
    # custom_result = custom_example()
    # print(f"\nCustom Result: {custom_result}")
    
    # The basic example runs automatically when the script is executed
    # because it is outside of any function definition.
    pass