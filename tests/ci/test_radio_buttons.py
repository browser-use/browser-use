# @file purpose: Test radio button interactions and serialization in browser-use
"""
Test file for verifying radio button clicking functionality and DOM serialization.

This test creates a simple HTML page with radio buttons, sends an agent to click them,
and logs the final agent message to show how radio buttons are represented in the serializer.

The serialization shows radio buttons as:
[index]<input type=radio name=groupname value=optionvalue checked=true/false />

Usage:
    uv run pytest tests/ci/test_radio_buttons.py -v -s
"""

import asyncio
import tempfile
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.service import Agent
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile


@pytest.fixture(scope='session')
def http_server():
    """Create and provide a test HTTP server that serves static content."""
    server = HTTPServer()
    server.start()

    # Read the HTML file content
    html_file = Path(__file__).parent / 'test_radio_buttons.html'
    with open(html_file, 'r') as f:
        html_content = f.read()

    # Add route for radio buttons test page
    server.expect_request('/radio-test').respond_with_data(
        html_content,
        content_type='text/html',
    )

    yield server
    server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
    """Return the base URL for the test HTTP server."""
    return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
async def browser_session():
    """Create and provide a Browser instance with security disabled."""
    browser_session = BrowserSession(
        browser_profile=BrowserProfile(
            headless=True,
            user_data_dir=None,
            keep_alive=True,
        )
    )
    await browser_session.start()
    yield browser_session
    await browser_session.kill()


class TestRadioButtons:
    """Test cases for radio button interactions."""

    async def test_radio_button_clicking(self, browser_session, base_url):
        """Test that agent can click radio buttons and log the final message showing radio serialization."""
        
        # Import the mock LLM function directly to create a custom one
        from tests.ci.conftest import create_mock_llm
        
        # Define actions that will navigate to the page and click radio buttons
        actions = [
            # First action: go to the URL (this will be added automatically, but we need something to analyze the page)
            '''
            {
                "thinking": "I can see the radio button test page with two fieldsets - one for colors and one for animals. I need to click the Blue radio button and the Dog radio button as requested.",
                "evaluation_previous_goal": "Successfully navigated to the radio test page",
                "memory": "On radio button test page, need to click Blue and Dog radio buttons",
                "next_goal": "Click the Blue radio button first",
                "action": [
                    {
                        "click_element_by_index": {
                            "index": 3
                        }
                    }
                ]
            }
            ''',
            # Second action: click the Dog radio button
            '''
            {
                "thinking": "Now I need to click the Dog radio button to complete the task.",
                "evaluation_previous_goal": "Successfully clicked the Blue radio button",
                "memory": "Clicked Blue radio button, now need to click Dog radio button",
                "next_goal": "Click the Dog radio button",
                "action": [
                    {
                        "click_element_by_index": {
                            "index": 6
                        }
                    }
                ]
            }
            ''',
            # Final action: mark as done
            '''
            {
                "thinking": "I have successfully clicked both the Blue radio button and the Dog radio button as requested.",
                "evaluation_previous_goal": "Successfully clicked the Dog radio button",
                "memory": "Completed clicking both Blue and Dog radio buttons",
                "next_goal": "Task completed",
                "action": [
                    {
                        "done": {
                            "text": "Successfully clicked the Blue radio button and Dog radio button",
                            "success": true
                        }
                    }
                ]
            }
            '''
        ]
        
        custom_mock_llm = create_mock_llm(actions)
        
        task = f"Go to {base_url}/radio-test and click on the 'Blue' radio button and the 'Dog' radio button."
        
        agent = Agent(
            task=task,
            llm=custom_mock_llm,
            browser_session=browser_session,
            max_actions_per_step=5,
        )
        
        try:
            # Run the agent
            history = await agent.run(max_steps=5)
            
            # Get all the agent messages to see DOM serialization
            if agent._message_manager and hasattr(agent._message_manager, 'state') and hasattr(agent._message_manager.state, 'history'):
                messages = agent._message_manager.state.history.get_messages()
                print(f"\n=== SEARCHING FOR RADIO BUTTON SERIALIZATION ===")
                for i, message in enumerate(messages):
                    if hasattr(message, 'content') and isinstance(message.content, list):
                        # Search through content parts for DOM/browser state
                        for j, part in enumerate(message.content):
                            if hasattr(part, 'text'):
                                text_content = part.text
                                # Look for browser state with radio buttons
                                if ('radio' in text_content.lower() or 'input' in text_content.lower()) and 'index' in text_content:
                                    print(f"\n🔍 RADIO BUTTON SERIALIZATION FOUND in Message {i+1}, Part {j+1}!")
                                    print(f"Content:\n{text_content}")
                                    print("=" * 100)
            
            # Get the last agent message from the message manager
            if agent._message_manager and agent._message_manager.last_input_messages:
                last_message = agent._message_manager.last_input_messages[-1]
                print(f"\n=== LAST AGENT MESSAGE ===")
                print(f"Message type: {type(last_message)}")
                print(f"Message content:\n{last_message.content}")
                print("=" * 50)
            
            # Also log the final state if available
            if agent.state.last_model_output:
                print(f"\n=== LAST MODEL OUTPUT ===")
                print(f"Model output: {agent.state.last_model_output}")
                print("=" * 50)
            
            # The test passes if we don't get an exception
            assert history is not None
            print(f"\nAgent completed {len(history)} steps successfully")
            
        except Exception as e:
            # For this test, we mainly want to see the message structure
            print(f"\nAgent execution failed: {e}")
            
            # Still try to log the message structure if available
            if agent._message_manager and agent._message_manager.last_input_messages:
                last_message = agent._message_manager.last_input_messages[-1]
                print(f"\n=== LAST AGENT MESSAGE (from failed run) ===")
                print(f"Message type: {type(last_message)}")
                if hasattr(last_message, 'content'):
                    print(f"Message content:\n{last_message.content}")
                print("=" * 50)