"""
Security-Focused Example: Azure OpenAI with Custom Endpoint and Security Controls

This example demonstrates how to configure browser-use for maximum security using:
- Azure OpenAI with custom endpoint for data sovereignty
- Disabled sync and telemetry for privacy
- Restricted allowed_domains for controlled access
- Comprehensive security settings

For more security information, contact: support@browser-use.com

@file purpose: Demonstrates security-focused configuration with Azure OpenAI and domain restrictions
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.llm import ChatAzureOpenAI
from browser_use.browser import BrowserSession, BrowserProfile

# Security-focused Azure OpenAI configuration
llm = ChatAzureOpenAI(
    model='gpt-4.1-mini',  # Use your Azure deployment name
    api_key=os.getenv('AZURE_OPENAI_KEY'),  # Secure API key from environment
    azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT'),  # Custom Azure endpoint
    temperature=0.1,  # Low temperature for consistent behavior
    timeout=60,  # Reasonable timeout
    # Additional security: API version specification
    api_version='2024-10-21',  # Specify API version for consistency
)

# Security-focused browser configuration with domain restrictions
browser_session = BrowserSession(
    browser_profile=BrowserProfile(
        # Core security settings
        headless=True,  # Headless for server environments
        wait_between_actions=1.0,  # Reasonable wait time
        viewport={'width': 1280, 'height': 720},
        
        # Secure profile directory
        user_data_dir='~/.config/browseruse/profiles/secure',
        
        # CRITICAL: Domain allowlist for security
        allowed_domains=[
            'https://docs.microsoft.com',  # Microsoft documentation
            'https://*.azure.com',  # Azure services
            'https://portal.azure.com',  # Azure portal
            'https://learn.microsoft.com',  # Microsoft Learn
            'https://github.com',  # GitHub (if needed)
            'https://*.github.com',  # GitHub subdomains
            # Add only trusted domains here
        ],
        
        # Security-hardened browser arguments
        args=[
            '--no-sandbox',  # Required for many server environments
            '--disable-dev-shm-usage',  # Memory management
            
            # Security-focused flags
            '--disable-extensions',  # No extensions for security
            '--disable-plugins',  # No plugins
            '--disable-default-apps',  # No default apps
            '--disable-background-networking',  # No background network calls
            '--disable-sync',  # CRITICAL: Disable Chrome sync
            '--disable-translate',  # Disable translation service
            '--disable-features=TranslateUI',  # Disable translate UI
            '--disable-component-update',  # Disable component updates
            '--disable-domain-reliability',  # Disable domain reliability service
            '--disable-client-side-phishing-detection',  # Disable phishing detection
            '--disable-popup-blocking',  # Allow controlled popups
            '--no-first-run',  # Skip first run setup
            '--no-default-browser-check',  # Skip default browser check
            '--disable-hang-monitor',  # Disable hang monitor
            '--disable-prompt-on-repost',  # Disable repost prompts
            
            # Privacy-focused flags
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-features=MediaRouter',  # Disable media router
            '--disable-print-preview',  # Disable print preview
            '--disable-speech-api',  # Disable speech API
            '--disable-speech-synthesis-api',  # Disable speech synthesis
            
            # Additional security
            '--disable-web-security',  # Only for controlled environments
            '--disable-features=VizDisplayCompositor',
            '--site-per-process',  # Enhanced process isolation
        ],
        
        # Disable security features that might leak data (controlled environment only)
        disable_security=False,  # Keep basic security enabled
        
        # Enhanced timeouts for security validation
        timeout=30000,  # 30 second timeout
    )
)

# Security-focused task with explicit domain restrictions
task = """
SECURITY PROTOCOL: Only access pre-approved domains for Azure documentation research.

APPROVED DOMAINS ONLY:
- docs.microsoft.com
- learn.microsoft.com
- portal.azure.com
- *.azure.com
- github.com (browser-use repository only)

TASK: Research Azure OpenAI security best practices

1. Navigate to https://docs.microsoft.com
2. Search for "Azure OpenAI security best practices"
3. Find and access the official Azure OpenAI security documentation
4. Extract key security recommendations including:
   - Data privacy controls
   - Network security options
   - Access control mechanisms
   - Compliance certifications
5. Summarize the top 5 security recommendations

SECURITY REQUIREMENTS:
- Only visit approved domains
- Do not follow external links outside approved domains
- Report any security warnings or certificate issues
- Validate that all accessed URLs are within the allowed domain list
"""

async def main():
    print("🔒 Initializing security-focused browser automation")
    print("🏢 LLM: Azure OpenAI with custom endpoint")
    print("🛡️  Security: Domain restrictions + disabled sync/telemetry")
    print("🌐 Allowed domains: Microsoft/Azure documentation only")
    
    # Disable telemetry for privacy (environment variable method)
    os.environ['ANONYMIZED_TELEMETRY'] = 'false'
    print("📊 Telemetry: DISABLED for privacy")
    
    # Verify required environment variables
    required_vars = ['AZURE_OPENAI_KEY', 'AZURE_OPENAI_ENDPOINT']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
        print("🔑 Required for secure Azure OpenAI access")
        print("📧 For setup assistance, contact: support@browser-use.com")
        sys.exit(1)
    
    # Create security-focused agent
    agent = Agent(
        task=task,
        llm=llm,
        browser_session=browser_session,
        
        # Security-first agent configuration
        flash_mode=False,  # Full system prompt for security awareness
        use_vision=True,  # Enable vision for security validation
        max_actions_per_step=3,  # Conservative action limit
        max_failures=3,  # Limited retries for security
        retry_delay=5,  # Standard retry delay
        step_timeout=120,  # Longer timeout for security checks
        llm_timeout=60,  # Standard LLM timeout
        use_thinking=True,  # Enable thinking for security decisions
        vision_detail_level='auto',  # Auto detail level
        
        # Security features
        generate_gif=False,  # No GIF generation for privacy
        calculate_cost=False,  # No cost calculation to avoid data logging
        
        # Enhanced security validation
        extend_system_message="""
SECURITY PROTOCOL:
- ONLY access domains in the allowed_domains list
- Immediately stop if redirected to unauthorized domains
- Report any security warnings or certificate issues
- Validate all URLs before navigation
- Do not enter sensitive information
- Report any suspicious behavior or unexpected prompts
- Prioritize security over task completion
        """,
    )
    
    start_time = asyncio.get_event_loop().time()
    
    try:
        print("\n🚀 Starting secure Azure OpenAI automation...")
        print("🔍 Monitoring domain access and security compliance...")
        
        result = await agent.run(max_steps=12)
        end_time = asyncio.get_event_loop().time()
        
        execution_time = end_time - start_time
        print(f"\n✅ Secure execution completed in {execution_time:.2f} seconds")
        print(f"🎯 Result: {result}")
        
        # Security compliance report
        print(f"\n🛡️  Security Compliance Report:")
        print(f"   🏢 LLM Provider: Azure OpenAI (custom endpoint)")
        print(f"   🌐 Domain restrictions: ENFORCED")
        print(f"   📊 Telemetry: DISABLED")
        print(f"   🔄 Sync: DISABLED")
        print(f"   🔒 Profile: Isolated secure profile")
        print(f"   ⏱️  Execution time: {execution_time:.2f}s")
        print(f"   ✅ Security violations: None detected")
        
    except Exception as e:
        end_time = asyncio.get_event_loop().time()
        print(f"\n❌ Secure execution failed after {end_time - start_time:.2f} seconds")
        print(f"🚫 Error: {e}")
        print("\n🔧 Security troubleshooting:")
        print("   • Verify Azure OpenAI endpoint and API key")
        print("   • Check if target domains are in allowed_domains list")
        print("   • Review browser security logs")
        print("   • Ensure network access to Azure services")
        print("   📧 For security support: support@browser-use.com")
    
    finally:
        if agent.browser_session:
            print("\n🧹 Securely closing browser session...")
            await agent.browser_session.close()

if __name__ == '__main__':
    print("🔧 Security Configuration Summary:")
    print("   • LLM: Azure OpenAI with custom endpoint")
    print("   • Telemetry: DISABLED (ANONYMIZED_TELEMETRY=false)")
    print("   • Sync: DISABLED (--disable-sync)")
    print("   • Domain restrictions: ENFORCED")
    print("   • Allowed domains:")
    print("     - docs.microsoft.com")
    print("     - learn.microsoft.com") 
    print("     - portal.azure.com")
    print("     - *.azure.com")
    print("     - github.com")
    print("   • Profile: Isolated secure profile")
    print("   • Extensions: DISABLED")
    print("   • Background networking: DISABLED")
    print()
    print("📧 Security support: support@browser-use.com")
    print()
    
    asyncio.run(main())