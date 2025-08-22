#!/usr/bin/env python3
"""
Demonstration of the new Python-based highlighting system.

This script shows how to:
1. Get browser state without script-based highlights 
2. Generate highlighted screenshots in Python
3. Filter highlights by include/exclude indices
4. Get both unhighlighted and highlighted images for merging

Usage: python examples/test_highlighting.py
"""

import asyncio
import base64
from pathlib import Path

from browser_use import Agent
from browser_use.browser.session import BrowserSession
from browser_use.llm import ChatOpenAI


async def demo_highlighting():
    """Demonstrate the new highlighting system."""
    print("🚀 Starting Python-based highlighting demonstration...")
    
    # Create browser session
    browser_session = BrowserSession()
    await browser_session.connect()
    await browser_session.attach_all_watchdogs()
    
    # Navigate to a test page  
    await browser_session.goto("https://example.com")
    print("📍 Navigated to example.com")
    
    # Get browser state (this now skips script injection!)
    print("📸 Getting browser state (no script injection)...")
    state = await browser_session.get_browser_state_summary(include_screenshot=True)
    
    print(f"✅ Found {len(state.dom_state.selector_map)} interactive elements")
    print(f"📊 Screenshot captured: {len(state.screenshot) if state.screenshot else 0} chars")
    
    # Generate highlighted screenshot with all elements
    print("🎨 Generating highlighted screenshot with all elements...")
    highlighted_all = state.get_highlighted_screenshot()
    
    if highlighted_all:
        print(f"✅ Highlighted screenshot generated: {len(highlighted_all)} chars")
        
        # Save to file for inspection
        output_dir = Path("highlighting_demo")
        output_dir.mkdir(exist_ok=True)
        
        with open(output_dir / "highlighted_all.png", "wb") as f:
            f.write(base64.b64decode(highlighted_all))
        print(f"💾 Saved highlighted image to {output_dir}/highlighted_all.png")
    
    # Demonstrate filtering - only show first 3 elements
    if state.dom_state.selector_map:
        indices = list(state.dom_state.selector_map.keys())
        include_subset = set(indices[:3]) if len(indices) >= 3 else set(indices)
        
        print(f"🎯 Generating filtered screenshot with elements: {include_subset}")
        highlighted_filtered = state.get_highlighted_screenshot(include_indices=include_subset)
        
        if highlighted_filtered:
            with open(output_dir / "highlighted_filtered.png", "wb") as f:
                f.write(base64.b64decode(highlighted_filtered))
            print(f"💾 Saved filtered image to {output_dir}/highlighted_filtered.png")
    
    # Demonstrate getting both versions at once
    print("🔄 Getting both unhighlighted and highlighted versions...")
    unhighlighted, highlighted = state.get_image_pair()
    
    if unhighlighted and highlighted:
        with open(output_dir / "unhighlighted.png", "wb") as f:
            f.write(base64.b64decode(unhighlighted))
        with open(output_dir / "highlighted_pair.png", "wb") as f:
            f.write(base64.b64decode(highlighted))
        print(f"💾 Saved image pair to {output_dir}/")
    
    # Show element summary
    from browser_use.dom.debug.python_highlights import get_element_summary
    summary = get_element_summary(state.dom_state.selector_map)
    print(f"📋 Element summary: {summary}")
    
    # Cleanup
    await browser_session.stop()
    print("✅ Demo completed successfully!")


if __name__ == "__main__":
    asyncio.run(demo_highlighting())