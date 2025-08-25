#!/usr/bin/env python3
"""
Simple test to check if the Gemini API key works.
"""

import os
import google.generativeai as genai

def test_api_key():
    """Test if the API key works with a simple request."""
    
    # Set the API key
    api_key = "AIzaSyA5_5u1A7ynST0rOn5QWrO1EH4sHqnyJVw"
    os.environ["GOOGLE_API_KEY"] = api_key
    
    try:
        # Configure the API
        genai.configure(api_key=api_key)
        
        # Test with a simple request
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content("Say hello in one word")
        
        print("✅ API Key Test SUCCESS!")
        print(f"Response: {response.text}")
        return True
        
    except Exception as e:
        print(f"❌ API Key Test FAILED: {e}")
        return False

if __name__ == "__main__":
    test_api_key() 