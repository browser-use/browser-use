"""
Integration tests for the DatePickerHandler with browser-use Agent.
Tests core date picker functionality.
"""

import asyncio
from datetime import datetime

import pytest
from langchain_openai import ChatOpenAI

from browser_use import Agent
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.actions import DatePickerAction

class DateFormat:
    """Common date formats"""
    ISO = "%Y-%m-%d"
    US = "%m/%d/%Y"

TEST_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Date Picker Test Page</title>
</head>
<body>
    <div class="test-section">
        <h3>Basic Date Input</h3>
        <input type="date" id="basic-date" name="basic-date">
    </div>
    
    <div class="test-section">
        <h3>Custom Format Date</h3>
        <input type="text" id="custom-date" placeholder="MM/DD/YYYY">
    </div>
</body>
</html>
"""

@pytest.fixture
async def agent():
    """Create a browser-use agent for testing"""
    llm = ChatOpenAI(
        model="gpt-4",
        temperature=0.0
    )
    config = BrowserConfig(headless=True)
    browser = Browser(config=config)
    agent = Agent(
        task="Test date picker interactions",
        llm=llm,
        browser=browser
    )
    yield agent
    if agent.browser:
        await agent.browser.close()

@pytest.fixture
async def test_page(agent):
    """Create a test page with date picker implementations"""
    context = await agent.browser.new_context()
    await context.create_new_tab()
    page = await context.get_current_page()
    await page.set_content(TEST_HTML)
    yield page
    await page.close()
    await context.close()

@pytest.fixture
async def date_picker(agent):
    """Create a DatePickerAction instance"""
    context = await agent.browser.new_context()
    await context.create_new_tab()
    yield DatePickerAction(context)
    await context.close()

@pytest.mark.asyncio
async def test_basic_date_input(date_picker, test_page):
    """Test basic HTML5 date input"""
    element = await test_page.wait_for_selector("#basic-date")
    date = datetime(2024, 2, 14)
    
    result = await date_picker.execute(
        element=element,
        date_value=date,
        format=DateFormat.ISO
    )
    
    assert result is True
    value = await element.input_value()
    assert value == "2024-02-14"

@pytest.mark.asyncio
async def test_custom_format(date_picker, test_page):
    """Test custom format date input"""
    element = await test_page.wait_for_selector("#custom-date")
    date = datetime(2024, 2, 14)
    
    result = await date_picker.execute(
        element=element,
        date_value=date,
        format=DateFormat.US
    )
    
    assert result is True
    value = await element.input_value()
    assert "02/14/2024" in value

@pytest.mark.asyncio
async def test_error_handling(date_picker, test_page):
    """Test basic error handling"""
    # Test with non-existent element
    result = await date_picker.execute(
        element="#non-existent",
        date_value=datetime(2024, 2, 14),
        format=DateFormat.ISO
    )
    assert result is False
    assert "Element not found" in str(date_picker.last_error)
    
    # Test with invalid date
    element = await test_page.wait_for_selector("#basic-date")
    result = await date_picker.execute(
        element=element,
        date_value="invalid date",
        format=DateFormat.ISO
    )
    assert result is False
    assert "Invalid date" in str(date_picker.last_error) 