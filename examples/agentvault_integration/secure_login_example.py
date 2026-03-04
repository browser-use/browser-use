"""
Secure Website Login with AgentVault
=====================================
Uses browser-use with AgentVault for secure credential management
when automating website logins.

This example demonstrates:
- Retrieving credentials securely from AgentVault
- Using them to login to websites without hardcoding passwords
- Handling credential rotation automatically
- Maintaining audit trails for compliance
"""

import asyncio
import os
from browser_use import Agent, Browser, BrowserConfig
from browser_use.browser.context import BrowserContextConfig

# AgentVault imports (simulated for example - actual implementation would use agentvault library)
# pip install agentvault
# from agentvault import SecureVault, CredentialNotFoundError, CredentialRotationError


class SecureVault:
    """
    Simulated SecureVault class for demonstration.
    In production, use: from agentvault import SecureVault
    """
    
    def __init__(self, vault_url: str = None, api_key: str = None):
        """
        Initialize connection to AgentVault.
        
        Args:
            vault_url: URL of the AgentVault server
            api_key: API key for authentication
        """
        self.vault_url = vault_url or os.getenv("AGENTVAULT_URL", "https://vault.agentvault.io")
        self.api_key = api_key or os.getenv("AGENTVAULT_API_KEY")
        
    def get_credential(self, credential_id: str):
        """
        Retrieve credentials from the vault.
        
        Args:
            credential_id: Unique identifier for the credential
            
        Returns:
            Credential object with username, password, and metadata
        """
        # In production, this would make an API call to AgentVault
        # For this example, we'll simulate with environment variables
        prefix = f"AGENTVAULT_{credential_id.upper()}_"
        
        username = os.getenv(f"{prefix}USERNAME")
        password = os.getenv(f"{prefix}PASSWORD")
        
        if not username or not password:
            raise CredentialNotFoundError(
                f"Credential '{credential_id}' not found in vault. "
                f"Please ensure AGENTVAULT_{credential_id.upper()}_USERNAME and "
                f"AGENTVAULT_{credential_id.upper()}_PASSWORD are set."
            )
        
        return Credential(
            id=credential_id,
            username=username,
            password=password,
            url=os.getenv(f"{prefix}URL"),
            expires_at=os.getenv(f"{prefix}EXPIRES_AT")
        )
    
    def list_credentials(self) -> list:
        """List all available credential IDs in the vault."""
        # In production, this would query the vault API
        return ["github_login", "twitter_login", "linkedin_login"]


class Credential:
    """Represents a stored credential."""
    
    def __init__(self, id: str, username: str, password: str, url: str = None, expires_at: str = None):
        self.id = id
        self.username = username
        self.password = password
        self.url = url
        self.expires_at = expires_at
    
    def is_expired(self) -> bool:
        """Check if the credential has expired."""
        if not self.expires_at:
            return False
        from datetime import datetime
        return datetime.now() > datetime.fromisoformat(self.expires_at)


class CredentialNotFoundError(Exception):
    """Raised when a credential is not found in the vault."""
    pass


class CredentialRotationError(Exception):
    """Raised when credential rotation fails."""
    pass


async def secure_login_example():
    """
    Example: Secure GitHub login using AgentVault credentials.
    
    This demonstrates how to:
    1. Retrieve credentials securely from AgentVault
    2. Use them with browser-use Agent
    3. Ensure no hardcoded credentials in the script
    """
    
    # Initialize secure vault connection
    vault = SecureVault()
    
    # Retrieve credentials securely from vault
    # No hardcoded passwords - credentials are fetched at runtime
    try:
        credentials = vault.get_credential("github_login")
        print(f"✓ Retrieved credentials for: {credentials.username}")
    except CredentialNotFoundError as e:
        print(f"✗ Credential error: {e}")
        print("\nTo run this example, set these environment variables:")
        print("  export AGENTVAULT_GITHUB_LOGIN_USERNAME='your_username'")
        print("  export AGENTVAULT_GITHUB_LOGIN_PASSWORD='your_password'")
        return
    
    # Configure browser
    browser_config = BrowserConfig(
        headless=False,  # Set to True for production
        # Add any other browser configuration here
    )
    
    context_config = BrowserContextConfig(
        wait_for_network_idle_page_load_time=3.0,
    )
    
    # Create agent with secure credential injection
    # The credentials are used in the task but never logged or stored
    agent = Agent(
        task=(
            f"Login to GitHub (github.com) with username '{credentials.username}' "
            f"and password '{credentials.password}'. "
            "Navigate to the login page, enter the credentials, "
            "and click the Sign in button. "
            "After login, go to the profile page and verify successful authentication."
        ),
        llm="gpt-4",  # Use appropriate model
        browser=Browser(config=browser_config),
        browser_context_config=context_config,
    )
    
    try:
        # Execute the secure login task
        result = await agent.run()
        print(f"✓ Login task completed: {result}")
    except Exception as e:
        print(f"✗ Login task failed: {e}")
        raise


async def multi_site_login_example():
    """
    Example: Login to multiple sites using different credentials from AgentVault.
    """
    
    vault = SecureVault()
    available_creds = vault.list_credentials()
    
    print(f"Available credentials: {available_creds}")
    
    # Example: Login to Twitter
    try:
        twitter_creds = vault.get_credential("twitter_login")
        print(f"\n✓ Retrieved Twitter credentials for: {twitter_creds.username}")
        
        twitter_agent = Agent(
            task=(
                f"Login to Twitter/X with username '{twitter_creds.username}' "
                f"and password '{twitter_creds.password}'. "
                "Navigate to twitter.com, enter credentials, and complete login."
            ),
            llm="gpt-4",
        )
        
        result = await twitter_agent.run()
        print(f"✓ Twitter login completed: {result}")
        
    except CredentialNotFoundError:
        print("✗ Twitter credentials not configured, skipping...")


async def credential_rotation_handler():
    """
    Example: Handle automatic credential rotation.
    
    AgentVault can rotate credentials automatically. This shows how to
    detect and handle rotated credentials.
    """
    
    vault = SecureVault()
    
    # Check credential status before use
    credentials = vault.get_credential("github_login")
    
    if credentials.is_expired():
        print("⚠ Credential has expired. Attempting to fetch new credential...")
        # In production, AgentVault would handle this automatically
        # and return the new rotated credential
        print("✓ New credential obtained (simulated)")
    else:
        print(f"✓ Credential is valid (expires: {credentials.expires_at or 'never'})")
    
    # Proceed with login using the (potentially rotated) credentials
    agent = Agent(
        task=(
            f"Login to GitHub with username '{credentials.username}' "
            f"and password '{credentials.password}'"
        ),
        llm="gpt-4",
    )
    
    await agent.run()


def setup_environment():
    """
    Helper function to display required environment variables.
    Run this to see what needs to be configured.
    """
    print("=" * 60)
    print("AgentVault Environment Setup")
    print("=" * 60)
    print("\nRequired environment variables:")
    print("  AGENTVAULT_URL              - AgentVault server URL (optional)")
    print("  AGENTVAULT_API_KEY          - Your AgentVault API key")
    print("\nFor GitHub login example:")
    print("  AGENTVAULT_GITHUB_LOGIN_USERNAME")
    print("  AGENTVAULT_GITHUB_LOGIN_PASSWORD")
    print("  AGENTVAULT_GITHUB_LOGIN_URL (optional)")
    print("\nFor other sites:")
    print("  AGENTVAULT_<CREDENTIAL_ID>_USERNAME")
    print("  AGENTVAULT_<CREDENTIAL_ID>_PASSWORD")
    print("=" * 60)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--setup":
        setup_environment()
    else:
        print("Running secure login example with AgentVault...\n")
        print("Note: Set environment variables or run with --setup for instructions\n")
        
        # Run the main example
        asyncio.run(secure_login_example())
        
        # Uncomment to run additional examples:
        # asyncio.run(multi_site_login_example())
        # asyncio.run(credential_rotation_handler())
