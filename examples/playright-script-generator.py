import asyncio
import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from langchain_anthropic import ChatAnthropic
from browser_use import Agent

# Print the API key (first few characters) to verify it's loaded
api_key = os.environ.get("ANTHROPIC_API_KEY", "")
if api_key:
    print(f"API key loaded: {api_key[:10]}...")
else:
    print("API key not found!")

# Define sensitive data to be filtered in logs and outputs
sensitive_data = {
    "username": "standard_user",
    "password": "secret_sauce"
}

# Initialize the Claude model
llm = ChatAnthropic(
    model="claude-3-opus-20240229",
    temperature=0.0,
    max_tokens=4096
)

# Test the LLM connection directly
try:
    print("Testing LLM connection...")
    result = llm.invoke("Hello, can you hear me?")
    print("LLM connection successful!")
    print(f"Response: {result.content[:50]}...")
except Exception as e:
    print(f"Error testing LLM connection: {e}")
    sys.exit(1)

task = 'Go to https://www.saucedemo.com/ and buy Sauce Labs Bike Light'

try:
    print("Creating Agent...")
    agent = Agent(task=task, llm=llm, sensitive_data=sensitive_data)
    print("Agent created successfully!")
except Exception as e:
    print(f"Error creating Agent: {e}")
    sys.exit(1)

async def main():
    try:
        print("Running agent...")
        history = await agent.run()
        
        # Extract Playwright actions to JSON
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        
        actions_path = output_dir / "playwright_actions.json"
        print(f"Extracting Playwright actions to: {actions_path}")
        actions = agent.extract_playwright_actions(output_path=actions_path)
        
        # Print a summary of the extracted actions
        print(f"Extracted {len(actions)} Playwright actions:")
        for i, action in enumerate(actions[:5], 1):
            print(f"  {i}. {action['action_name']}")
        if len(actions) > 5:
            print(f"  ... and {len(actions) - 5} more actions")
        
        # Generate a Playwright script with a descriptive name
        print("\nGenerating Playwright script...")
        script_name = "sauce_demo_purchase"
        script = await agent.generate_playwright_script(
            actions=actions,
            headless=False,
            script_name=script_name
        )
        
        # Get the output path from the logger output
        script_path = None
        for handler in logging.getLogger().handlers:
            if isinstance(handler, logging.StreamHandler):
                for record in handler.records:
                    if "Playwright script saved to" in record.getMessage():
                        script_path = record.getMessage().split("Playwright script saved to ")[1]
                        break
        
        if not script_path:
            script_path = "See output directory for the generated script"
            
        # Print a preview of the generated script
        print(f"\nGenerated Playwright script preview:")
        script_lines = script.split('\n')
        preview_lines = min(10, len(script_lines))
        for i in range(preview_lines):
            print(script_lines[i])
        print("...")
        
        print(f"\nFull script saved to: {script_path}")
        print(f"\nYou can run this script with: python {script_path}")
            
    except Exception as e:
        print(f"Error running agent: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(main())
