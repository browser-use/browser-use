"""
Example: Custom Interactive Selectors Demo

This example creates a simple HTML page with custom interactive elements
and demonstrates how the custom_interactive_selectors feature allows the
agent to interact with elements that wouldn't normally be detected.
"""

import asyncio
import tempfile
import os
from pathlib import Path
from browser_use import Agent, ChatOpenAI


def create_demo_html():
    """Create a demo HTML page with custom interactive elements."""
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Custom Interactive Elements Demo</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        
        /* Standard interactive elements */
        .standard-button {
            background: #007bff;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            margin: 10px;
        }
        
        /* Custom elements that look interactive but aren't standard */
        .custom-card {
            background: #e9ecef;
            padding: 20px;
            margin: 10px 0;
            border-radius: 8px;
            border-left: 4px solid #28a745;
            transition: background-color 0.3s;
        }
        
        .special-widget {
            background: linear-gradient(45deg, #ff6b6b, #4ecdc4);
            color: white;
            padding: 15px;
            margin: 10px 0;
            border-radius: 10px;
            text-align: center;
            font-weight: bold;
        }
        
        .interactive-icon {
            display: inline-block;
            width: 40px;
            height: 40px;
            background: #ffc107;
            border-radius: 50%;
            margin: 5px;
            text-align: center;
            line-height: 40px;
            font-weight: bold;
        }
        
        .result {
            margin-top: 20px;
            padding: 15px;
            background: #d4edda;
            border: 1px solid #c3e6cb;
            border-radius: 5px;
            display: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Custom Interactive Elements Demo</h1>
        <p>This page demonstrates elements that might not be automatically detected as interactive.</p>
        
        <h2>Standard Interactive Elements</h2>
        <button class="standard-button" onclick="showResult('Standard button clicked!')">Standard Button</button>
        <a href="#" onclick="showResult('Standard link clicked!'); return false;">Standard Link</a>
        
        <h2>Custom Interactive Elements</h2>
        <p>These elements have click handlers but might not be detected automatically:</p>
        
        <div class="custom-card" data-action="click" onclick="showResult('Custom card clicked!')">
            <h3>Custom Card Component</h3>
            <p>This looks like a card but has a click handler (data-action attribute)</p>
        </div>
        
        <div class="special-widget" id="special-element" onclick="showResult('Special widget clicked!')">
            <p>Special Widget (ID: special-element)</p>
        </div>
        
        <div>
            <span class="interactive-icon" data-action="icon1" onclick="showResult('Icon 1 clicked!')">1</span>
            <span class="interactive-icon" data-action="icon2" onclick="showResult('Icon 2 clicked!')">2</span>
            <span class="interactive-icon" data-action="icon3" onclick="showResult('Icon 3 clicked!')">3</span>
        </div>
        
        <div role="custom-button" onclick="showResult('Custom role button clicked!')" 
             style="background: #6f42c1; color: white; padding: 12px; margin: 10px 0; text-align: center; border-radius: 5px;">
            Element with Custom Role
        </div>
        
        <div id="result" class="result"></div>
    </div>
    
    <script>
        function showResult(message) {
            const resultDiv = document.getElementById('result');
            resultDiv.textContent = message;
            resultDiv.style.display = 'block';
            setTimeout(() => {
                resultDiv.style.display = 'none';
            }, 3000);
        }
    </script>
</body>
</html>
    """
    
    # Create a temporary HTML file
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False)
    temp_file.write(html_content)
    temp_file.close()
    
    return temp_file.name


async def demo_without_custom_selectors():
    """Run the demo without custom selectors to show the difference."""
    print("🔍 Demo 1: Running WITHOUT custom selectors")
    print("=" * 50)
    
    html_file = create_demo_html()
    file_url = f"file://{os.path.abspath(html_file)}"
    
    try:
        agent = Agent(
            task=f"Open {file_url} and try to click on the 'Custom Card Component' and the 'Special Widget'",
            llm=ChatOpenAI(model="gpt-4o-mini"),
            headless=True,
        )
        
        result = await agent.run(max_steps=5)
        print("✅ Demo 1 completed")
        
    finally:
        # Clean up
        os.unlink(html_file)


async def demo_with_custom_selectors():
    """Run the demo with custom selectors to show the improvement."""
    print("\n🎯 Demo 2: Running WITH custom selectors")
    print("=" * 50)
    
    html_file = create_demo_html()
    file_url = f"file://{os.path.abspath(html_file)}"
    
    # Define the custom selectors that match our demo page elements
    custom_selectors = [
        '.custom-card',              # The custom card component
        '#special-element',          # The special widget
        '[data-action]',            # Any element with data-action attribute
        '[role="custom-button"]',   # Elements with custom role
    ]
    
    try:
        agent = Agent(
            task=f"Open {file_url} and click on the 'Custom Card Component', the 'Special Widget', and one of the numbered icons",
            llm=ChatOpenAI(model="gpt-4o-mini"),
            custom_interactive_selectors=custom_selectors,
            headless=True,
        )
        
        print("Custom selectors being used:")
        for selector in custom_selectors:
            print(f"  - {selector}")
        
        result = await agent.run(max_steps=8)
        print("✅ Demo 2 completed")
        
    finally:
        # Clean up
        os.unlink(html_file)


async def main():
    """Run both demos to show the difference."""
    print("🚀 Custom Interactive Selectors Demo")
    print("This demo shows the difference between running with and without custom selectors")
    print()
    
    # Run demo without custom selectors first
    await demo_without_custom_selectors()
    
    # Run demo with custom selectors
    await demo_with_custom_selectors()
    
    print("\n📊 Summary:")
    print("- Demo 1 (without custom selectors): May have trouble finding non-standard interactive elements")
    print("- Demo 2 (with custom selectors): Can interact with custom elements that match the specified selectors")
    print("\n💡 Use custom_interactive_selectors when working with:")
    print("  • Custom UI frameworks (React, Vue, Angular components)")
    print("  • Web apps with non-standard interactive patterns")
    print("  • Elements that have click handlers but don't look like standard buttons/links")


if __name__ == "__main__":
    asyncio.run(main())