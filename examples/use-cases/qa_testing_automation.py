"""
QA Testing Use Case: Automated Web Application Testing

This example demonstrates how QA engineers can use browser-use for:
- Automated functional testing of web applications
- User journey validation
- Form testing and data validation
- Cross-browser compatibility checks
- Regression testing automation

Perfect for continuous integration, smoke tests, and comprehensive QA workflows.

@file purpose: Demonstrates QA testing automation for web application validation
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatOpenAI
from browser_use.browser import BrowserSession, BrowserProfile

# QA testing optimized LLM configuration
llm = ChatOpenAI(
    model='gpt-4.1-mini',  # Good for detailed testing instructions
    temperature=0.0,  # Zero temperature for deterministic test execution
    timeout=60,  # Standard timeout for testing
)

# Set up test results directory
test_results_dir = Path.home() / 'qa_test_results'
test_results_dir.mkdir(parents=True, exist_ok=True)

# QA testing browser configuration
browser_session = BrowserSession(
    browser_profile=BrowserProfile(
        headless=False,  # Visible browser for test observation and debugging
        wait_between_actions=1.0,  # Standard wait for stable testing
        viewport={'width': 1920, 'height': 1080},  # Full HD for comprehensive testing
        
        # Persistent profile for test consistency
        user_data_dir='~/.config/browseruse/profiles/qa_testing',
        
        # QA testing optimized settings
        args=[
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--start-maximized',  # Full screen for complete UI testing
            '--disable-infobars',
            '--disable-popup-blocking',  # Allow test popups
            '--disable-default-apps',
            '--no-first-run',
            '--disable-background-timer-throttling',  # Ensure timers work in tests
            '--disable-backgrounding-occluded-windows',  # Keep test tabs active
            '--disable-renderer-backgrounding',  # Maintain performance during tests
            '--enable-automation',  # Clear automation mode for testing
            '--disable-web-security',  # For testing cross-origin scenarios (controlled env)
        ],
        
        # Deterministic rendering for consistent test results
        deterministic_rendering=True,  # Enable for QA consistency
        
        # Extended timeouts for thorough testing
        timeout=60000,  # 60 second timeout for complex pages
    )
)

# Comprehensive QA testing task
task = """
QA TESTING AUTOMATION: Comprehensive Web Application Testing Suite

You are a QA engineer conducting automated testing of web applications. Execute comprehensive test scenarios to validate functionality, usability, and reliability.

TARGET APPLICATION: GitHub.com (as a representative web application)

TESTING OBJECTIVES:
1. User authentication and session management
2. Search functionality and results validation
3. Navigation and UI element testing
4. Form validation and error handling
5. Responsive design and accessibility
6. Performance and loading behavior

TEST EXECUTION PLAN:

TEST SUITE 1: Authentication and Session Management
1. Navigate to https://github.com
2. Test login flow:
   - Click "Sign in" button
   - Validate login form appears
   - Test form validation (empty fields)
   - Verify error messages display correctly
   - Test "Forgot password" link functionality
   - Validate form accessibility (tab navigation)
3. Test without logging in:
   - Verify public content is accessible
   - Check that restricted features show appropriate prompts

TEST SUITE 2: Search Functionality Testing
1. Test main search functionality:
   - Use search bar with valid query: "browser-use"
   - Validate search results page loads
   - Verify results are relevant and properly formatted
   - Test search filters (repositories, code, users, etc.)
   - Validate pagination if present
2. Test edge cases:
   - Empty search query
   - Special characters in search
   - Very long search terms
   - Non-existent search terms

TEST SUITE 3: Navigation and UI Element Testing
1. Test main navigation:
   - Verify all main menu items are clickable
   - Test dropdown menus functionality
   - Validate breadcrumb navigation
   - Test back/forward browser navigation
2. Test responsive elements:
   - Resize browser window to test responsive design
   - Test mobile viewport simulation
   - Verify hamburger menu on smaller screens

TEST SUITE 4: Repository Page Testing
1. Navigate to a popular repository (e.g., microsoft/vscode)
2. Test repository features:
   - Verify README.md renders correctly
   - Test file browser navigation
   - Validate star/watch button functionality (UI only)
   - Test issue and pull request tabs
   - Verify code syntax highlighting
   - Test file download functionality

TEST SUITE 5: Form Validation and Error Handling
1. Test repository creation form (if accessible):
   - Test required field validation
   - Test input length limits
   - Test special character handling
   - Verify error message clarity and positioning
2. Test comment forms:
   - Navigate to an issue or pull request
   - Test comment form validation
   - Test markdown preview functionality

TEST SUITE 6: Performance and Accessibility Testing
1. Performance checks:
   - Measure page load times
   - Verify images load properly
   - Test for broken links
   - Check for JavaScript errors in console
2. Accessibility validation:
   - Test keyboard navigation (Tab key)
   - Verify alt text on images
   - Check heading structure (H1, H2, etc.)
   - Test focus indicators

TEST REPORTING REQUIREMENTS:
For each test:
- Record PASS/FAIL status
- Document any bugs or issues found
- Capture screenshots of failures
- Note performance metrics
- Record accessibility violations
- Document browser console errors

VALIDATION CRITERIA:
- All UI elements should be functional and responsive
- Forms should provide clear validation feedback
- Navigation should be intuitive and consistent
- Search results should be accurate and well-formatted
- Page load times should be reasonable (< 5 seconds)
- No JavaScript errors in console
- Accessibility standards should be met

ERROR HANDLING:
- If a test fails, document the failure and continue with next test
- Take screenshots of any error states
- Report unexpected behavior or UI inconsistencies
- Note any performance degradation or timeouts
"""

async def main():
    print("🧪 Initializing QA Testing Automation Suite")
    print("🎯 Target Application: GitHub.com")
    print("📋 Test Suites: Authentication, Search, Navigation, Forms, Performance, Accessibility")
    print("📁 Test Results Directory:", str(test_results_dir))
    
    # Create test session timestamp
    test_session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"🔍 Test Session ID: {test_session_id}")
    
    # Create QA testing agent
    agent = Agent(
        task=task,
        llm=llm,
        browser_session=browser_session,
        
        # QA testing optimized settings
        flash_mode=False,  # Full prompts for comprehensive testing
        use_vision=True,  # Critical for UI validation
        max_actions_per_step=5,  # Moderate actions for thorough testing
        max_failures=5,  # More retries for flaky tests
        retry_delay=3,  # Quick retry for test efficiency
        step_timeout=120,  # Extended timeout for complex test scenarios
        llm_timeout=60,  # Standard timeout for test analysis
        use_thinking=True,  # Enable thinking for test logic
        vision_detail_level='high',  # High detail for UI accuracy
        
        # QA testing features
        generate_gif=True,  # Generate GIF for test documentation
        calculate_cost=False,  # No cost calculation for testing
        
        # Enhanced validation
        validate_output=True,  # Validate test results
        
        # QA testing system prompt enhancement
        extend_system_message="""
QA TESTING PROTOCOL:
- Execute tests systematically and document all results
- Take screenshots of any failures or unexpected behavior
- Validate UI elements are properly positioned and functional
- Test both positive and negative scenarios
- Report accessibility issues and performance problems
- Document exact steps to reproduce any bugs found
- Verify error messages are clear and helpful
- Test edge cases and boundary conditions
- Maintain consistent test execution methodology
- Focus on user experience and usability
- Report any security concerns or vulnerabilities observed
        """,
    )
    
    start_time = asyncio.get_event_loop().time()
    
    try:
        print("\n🚀 Starting QA testing automation...")
        print("📋 Executing comprehensive test suite...")
        print("🔍 Monitoring for bugs, performance issues, and accessibility violations...")
        
        result = await agent.run(max_steps=30)  # Extended steps for comprehensive testing
        end_time = asyncio.get_event_loop().time()
        
        execution_time = end_time - start_time
        print(f"\n✅ QA testing suite completed in {execution_time:.2f} seconds")
        
        # Generate test report
        test_report_file = test_results_dir / f"qa_test_report_{test_session_id}.txt"
        with open(test_report_file, 'w') as f:
            f.write(f"QA Test Report - Session {test_session_id}\n")
            f.write(f"{'='*50}\n\n")
            f.write(f"Test Execution Time: {execution_time:.2f} seconds\n")
            f.write(f"Target Application: GitHub.com\n")
            f.write(f"Test Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("Test Results:\n")
            f.write(f"{result}\n\n")
        
        print(f"\n📊 QA Testing Results:")
        print(f"   🎯 Test suite: Comprehensive web application testing")
        print(f"   ⏱️  Execution time: {execution_time:.2f}s")
        print(f"   📁 Test report: {test_report_file}")
        print(f"   🖼️  Test GIF: Generated for visual validation")
        print(f"   📋 Results: {result}")
        
        # QA recommendations
        print(f"\n🔄 QA Process Recommendations:")
        print(f"   1. Review test report for identified issues")
        print(f"   2. Create bug tickets for any failures found")
        print(f"   3. Add failing scenarios to regression test suite")
        print(f"   4. Schedule regular automated test runs")
        print(f"   5. Integrate with CI/CD pipeline for continuous testing")
        
    except Exception as e:
        end_time = asyncio.get_event_loop().time()
        print(f"\n❌ QA testing automation failed after {end_time - start_time:.2f} seconds")
        print(f"🚫 Error: {e}")
        print("\n🔧 QA Testing Troubleshooting:")
        print("   • Verify target application is accessible")
        print("   • Check browser compatibility and version")
        print("   • Ensure test environment is stable")
        print("   • Review test data and prerequisites")
        print("   • Validate network connectivity")
        print("   • Check for application maintenance windows")
        
        # Create failure report
        failure_report_file = test_results_dir / f"qa_test_failure_{test_session_id}.txt"
        with open(failure_report_file, 'w') as f:
            f.write(f"QA Test Failure Report - Session {test_session_id}\n")
            f.write(f"{'='*50}\n\n")
            f.write(f"Failure Time: {end_time - start_time:.2f} seconds\n")
            f.write(f"Error: {e}\n")
            f.write(f"Test Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        print(f"\n📁 Failure report saved: {failure_report_file}")
    
    finally:
        if agent.browser_session:
            print("\n🧹 Closing QA testing session...")
            await agent.browser_session.close()

if __name__ == '__main__':
    print("🔧 QA Testing Configuration:")
    print("   • Test Target: GitHub.com (representative web application)")
    print("   • Test Types: Functional, UI, Performance, Accessibility")
    print("   • Browser: Visible mode with deterministic rendering")
    print("   • Validation: Comprehensive UI and UX testing")
    print("   • Documentation: Automated test reports and GIF recording")
    print("   • Error Handling: Detailed failure analysis and reporting")
    print()
    
    # Verify OpenAI API key
    if not os.getenv('OPENAI_API_KEY'):
        print("❌ OPENAI_API_KEY environment variable not set!")
        print("🔑 Required for QA testing automation")
        sys.exit(1)
    
    # Verify test results directory
    if not test_results_dir.exists():
        print(f"❌ Test results directory not accessible: {test_results_dir}")
        sys.exit(1)
    
    asyncio.run(main())