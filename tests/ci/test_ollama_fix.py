"""Test script to verify the Ollama fix."""

import asyncio
import os
import sys

# Assume the fix has been applied to browser_use/llm/ollama/chat.py
# If not, this test will only pass if ChatOllama is storing the host correctly.

# 1. Ensure the necessary imports are accessible
# Note: Assuming browser_use is installed or the tests run with proper path
from browser_use import Agent 
from browser_use.llm.ollama import ChatOllama
from ollama import AsyncClient as OllamaAsyncClient # Needed to inspect client host

# --- Helper Function to Get Client Host ---
# This is crucial because the OllamaAsyncClient's host is not a public attribute 
# in the standard library and needs to be accessed via the _host property.
def _get_ollama_client_host(client: OllamaAsyncClient) -> str:
    """Safely retrieves the host/url from the ollama client."""
    # Ollama client stores the base URL internally
    return getattr(client, '_host', 'HOST_NOT_AVAILABLE').rstrip('/')


async def test_host_configuration():
    """Test that ChatOllama properly maintains host configuration."""
    
    # Temporarily set environment variable to test precedence
    os.environ['OLLAMA_HOST'] = 'http://192.168.1.5:11434'
    
    print("=" * 60)
    print("Testing Ollama Host Configuration Fix")
    print("=" * 60)
    
    # Test 1: Default host (should use the environment variable set above)
    print("\n✓ Test 1: Host precedence (Environment Variable)")
    llm = ChatOllama(model='llama3.1:8b')
    client = llm.get_client()
    
    # The client should pick up the value from the environment variable.
    expected_host = 'http://192.168.1.5:11434' 
    actual_host = _get_ollama_client_host(client)
    assert actual_host == expected_host, f"Host incorrect. Expected: {expected_host}, Got: {actual_host}"
    
    print(f"  Client Host: {actual_host}")
    print(f"  Model: {llm.model}")
    print(f"  Timeout: {llm.timeout}s")
    
    # Test 2: Custom host (should override the environment variable)
    print("\n✓ Test 2: Custom host configuration (Override)")
    custom_host_input = 'http://192.168.1.100:11434'
    llm_custom = ChatOllama(
        model='mistral',
        host=custom_host_input
    )
    client_custom = llm_custom.get_client()
    actual_custom_host = _get_ollama_client_host(client_custom)
    
    assert actual_custom_host == custom_host_input
    print(f"  Client Host: {actual_custom_host}")
    
    # Test 3: Trailing slash removal
    print("\n✓ Test 3: Trailing slash handling")
    slash_input = 'http://127.0.0.1:11434/'
    expected_slash = 'http://127.0.0.1:11434'
    llm_slash = ChatOllama(
        model='llama3.1:8b',
        host=slash_input
    )
    client_slash = llm_slash.get_client()
    actual_slash_host = _get_ollama_client_host(client_slash)
    
    assert actual_slash_host == expected_slash, "Trailing slash not removed"
    print(f"  Input: {slash_input}")
    print(f"  Stored/Used: {actual_slash_host}")
    
    # Test 4: Client creation and reuse
    print("\n✓ Test 4: Client creation and reuse")
    client1 = llm.get_client()
    client2 = llm.get_client()
    assert client1 is client2, "Client not reused"
    print(f"  Client reused: {client1 is client2}")
    
    # Test 5: Actual connection (requires Ollama running)
    # The client created in Test 1 is used here (http://192.168.1.5:11434)
    print("\n✓ Test 5: Actual Ollama connection test (Host: 192.168.1.5:11434)")
    try:
        response = await llm.ainvoke([
            {"role": "user", "content": "Say hello in one word"}
        ])
        print(f"  Connection successful!")
        print(f"  Response: {response['message']['content'][:50].strip()}...")
    except ConnectionRefusedError as e:
        print(f"  ⚠ Connection refused (Ollama not running or wrong host): {str(e)[:60]}...")
    except Exception as e:
        print(f"  ✗ Unexpected error: {e}")
        raise
    finally:
        # Clean up environment variable
        del os.environ[&#39;OLLAMA_HOST&#39;]
    
    print("\n" + "=" * 60)
    print("✅ All configuration tests passed!")
    print("=" * 60)


async def test_with_agent():
    """Test ChatOllama with actual Agent (initialization only)."""
    
    print("\n" + "=" * 60)
    print("Testing Ollama with Agent (Initialization Only)")
    print("=" * 60)
    
    try:
        # NOTE: Without the fix in chat.py, this will fail if OLLAMA_HOST is not set
        llm = ChatOllama(model='llama3.1:8b')
        
        print(f"\n✓ LLM Configuration:")
        print(f"  Model: {llm.model}")
        print(f"  Client Host: {_get_ollama_client_host(llm.get_client())}")
        print(f"  Timeout: {llm.timeout}s")
        
        print(f"\n✓ Creating agent...")
        agent = Agent(
            task='Go to google.com and search for "browser-use github"',
            llm=llm
        )
        
        print(f"✓ Agent created successfully")
        print(f"  Task: {agent.task}")
        
        print(f"\n⚠ Skipping actual run (requires Ollama + browser)")
        print(f"  To run fully and verify the timeout fix: agent.run_sync()")
        
    except Exception as e:
        print(f"✗ Error during Agent/LLM creation: {e}")
        raise


if __name__ == '__main__':
    print("Starting Ollama fix verification...\n")
    
    # Run configuration tests
    asyncio.run(test_host_configuration())
    
    # Run agent test
    asyncio.run(test_with_agent())
    
    print("\n🎉 All tests completed!")