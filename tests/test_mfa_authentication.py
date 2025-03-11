import os
import pytest
import asyncio
from typing import Dict, List
from langchain_openai import ChatOpenAI
from browser_use.agent.service import Agent
from browser_use.controller.service import Controller


MFA_URL = "https://seleniumbase.io/realworld/login"
MFA_SIGNUP_URL = "https://seleniumbase.io/realworld/signup"  # URL to get the QR code for MFA setup

@pytest.mark.asyncio
async def test_mfa_authentication_flow():
    """
    Test that the agent can complete an authentication flow that includes MFA verification
    """
    llm = ChatOpenAI(model='gpt-4o-mini')
    # Create controller and agent
    controller = Controller()
    # Define test credentials
    test_credentials = {
        "username": "demo_user",
        "password": "secret_pass"
    }
    task = f"Complete the sign-in process on the {MFA_URL} webpage. First, enter the username and password. " \
             f"Then, when you reach the MFA verification step, get the MFA code from the user and enter it. "\
             f"Finally, verify that the authentication was successful. The username is " \
             f"{test_credentials['username']} and the password is {test_credentials['password']}."
    # Add note about MFA setup
    print(f"\nNOTE: Before running this test, you should visit {MFA_SIGNUP_URL} to set up Google Authenticator \
          with the QR code provided there or use the OTP code provided there.\n")
    
    agent = Agent(controller=controller, llm=llm, task=task, sensitive_data=test_credentials)
    
    result = await agent.run()

    agent_message = None
    if result.is_done:
        agent_message = result.history[-1].result[0].extracted_content
    else:
        agent_message = result.history[-1].result[0].error

    assert agent_message is not None, "Agent failed to complete MFA authentication task"

if __name__ == "__main__":
    asyncio.run(test_mfa_authentication_flow()) 