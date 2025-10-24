"""
Example: Custom Interactive Selectors

This example demonstrates how to use custom_interactive_selectors to force
certain elements to be marked as interactive, even if they wouldn't normally
be detected as clickable by the browser-use agent.

This is useful for:
- Custom UI components that don't use standard interactive tags
- Elements with non-standard click handlers
- Complex web applications with custom interaction patterns
"""

import asyncio
from browser_use import Agent, ChatOpenAI


async def main():
    """
    Example showing how to specify custom selectors that should always be
    treated as interactive elements.
    """
    
    # Define custom selectors that should always be marked as interactive
    custom_selectors = [
        '.custom-button',           # Any element with class "custom-button"
        '[data-action]',           # Any element with a "data-action" attribute
        '#special-element',        # Element with ID "special-element"
        'div.interactive-card',    # Div elements with class "interactive-card"
        '[role="custom-button"]',  # Elements with custom role attribute
    ]
    
    # Create agent with custom interactive selectors
    agent = Agent(
        task="Navigate to a webpage and interact with custom UI components that might not be automatically detected as clickable",
        llm=ChatOpenAI(model="gpt-4o-mini"),
        custom_interactive_selectors=custom_selectors,
        # You can also pass other browser configuration options
        headless=False,  # Set to True for headless mode
    )
    
    print("🎯 Agent created with custom interactive selectors:")
    for selector in custom_selectors:
        print(f"  - {selector}")
    
    print("\n🚀 Running agent...")
    print("The agent will now treat elements matching the custom selectors as interactive,")
    print("even if they wouldn't normally be detected as clickable.")
    
    # Run the agent
    result = await agent.run(max_steps=10)
    
    print("✅ Agent completed!")
    return result


if __name__ == "__main__":
    asyncio.run(main())