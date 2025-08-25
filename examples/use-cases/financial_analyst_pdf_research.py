"""
Financial Analyst Use Case: Automated PDF Research and Download

This example demonstrates how a financial analyst can use browser-use to:
- Search for financial reports and research documents
- Identify and download relevant PDFs
- Extract key information from financial websites
- Organize downloaded documents for analysis

Perfect for equity research, due diligence, and market analysis workflows.

@file purpose: Demonstrates financial analyst workflow for PDF research and document collection
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatOpenAI
from browser_use.browser import BrowserSession, BrowserProfile

# Financial analyst optimized LLM configuration
llm = ChatOpenAI(
    model='gpt-4.1-mini',  # Good balance of capability and cost for research
    temperature=0.2,  # Low temperature for consistent, analytical behavior
    timeout=90,  # Longer timeout for complex financial analysis
)

# Set up downloads directory for financial documents
downloads_dir = Path.home() / 'Downloads' / 'financial_research'
downloads_dir.mkdir(parents=True, exist_ok=True)

# Financial analyst browser configuration
browser_session = BrowserSession(
    browser_profile=BrowserProfile(
        headless=False,  # Visible browser for analyst review
        wait_between_actions=1.5,  # Reasonable wait for page loads
        viewport={'width': 1600, 'height': 900},  # Large viewport for financial data
        
        # Persistent profile for bookmarks and saved logins
        user_data_dir='~/.config/browseruse/profiles/financial_analyst',
        
        # Downloads configuration
        downloads_path=str(downloads_dir),
        
        # Financial research optimized settings
        args=[
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--start-maximized',  # Full screen for better data visibility
            '--disable-infobars',
            '--disable-popup-blocking',  # Allow PDF downloads
            '--disable-default-apps',
            '--no-first-run',
            '--enable-automation',  # Clear automation mode for transparency
        ],
        
        # Standard timeouts for financial sites
        timeout=45000,
    )
)

# Financial analyst research task
task = """
FINANCIAL ANALYST RESEARCH TASK: Automated PDF Collection and Analysis

You are a financial analyst conducting research on technology companies. Your task is to find and download relevant financial documents and research reports.

TARGET COMPANIES: Microsoft (MSFT), Apple (AAPL), Google/Alphabet (GOOGL)

RESEARCH OBJECTIVES:
1. Find recent quarterly earnings reports (10-Q)
2. Locate annual reports (10-K) 
3. Download analyst research reports
4. Collect investor presentations
5. Find ESG/sustainability reports

EXECUTION PLAN:

PHASE 1: SEC EDGAR Database Research
1. Navigate to https://www.sec.gov/edgar/searchedgar/companysearch.html
2. Search for each target company by ticker symbol
3. Find and download recent 10-K and 10-Q filings
4. For each company, download:
   - Most recent 10-K (annual report)
   - Most recent 10-Q (quarterly report)
   - Latest proxy statement (DEF 14A)

PHASE 2: Company Investor Relations
1. Visit each company's official investor relations page:
   - Microsoft: https://www.microsoft.com/en-us/Investor
   - Apple: https://investor.apple.com
   - Alphabet: https://abc.xyz/investor/
2. Download latest earnings presentations
3. Find and download sustainability/ESG reports
4. Collect any recent investor day presentations

PHASE 3: Financial Research Platforms
1. Visit Yahoo Finance for each company
2. Look for analyst reports and research notes
3. Download any available PDF research documents
4. Collect consensus estimates and analyst ratings

PHASE 4: Document Organization and Summary
1. Create a summary of all downloaded documents
2. List document types, dates, and key metrics found
3. Organize files by company and document type
4. Provide analysis-ready document inventory

DOWNLOAD REQUIREMENTS:
- Only download legitimate financial documents (PDFs)
- Verify document authenticity and source
- Check file sizes (typical range: 500KB - 50MB for financial PDFs)
- Rename files with clear naming convention: [Company]_[Document_Type]_[Date].pdf
- Report any download failures or access issues

COMPLIANCE NOTES:
- Only access publicly available documents
- Respect website terms of service
- Do not attempt to access restricted or paid content
- Verify all sources are legitimate financial institutions or official company pages

ANALYSIS FOCUS:
- Revenue growth trends
- Profitability metrics
- Cash flow analysis
- Market position and competition
- ESG initiatives and sustainability metrics
"""

async def main():
    print("📊 Initializing Financial Analyst PDF Research Automation")
    print("🏢 Target Companies: Microsoft, Apple, Google/Alphabet")
    print("📁 Downloads Directory:", str(downloads_dir))
    print("🔍 Research Focus: Financial reports, earnings, ESG documents")
    
    # Verify downloads directory
    if not downloads_dir.exists():
        print(f"❌ Downloads directory not accessible: {downloads_dir}")
        sys.exit(1)
    
    # Create financial analyst agent
    agent = Agent(
        task=task,
        llm=llm,
        browser_session=browser_session,
        
        # Financial analyst optimized settings
        flash_mode=False,  # Full prompts for comprehensive analysis
        use_vision=True,  # Important for reading financial charts and tables
        max_actions_per_step=4,  # Moderate actions for careful document handling
        max_failures=3,  # Reasonable retries for network issues
        retry_delay=8,  # Longer delay for financial sites
        step_timeout=150,  # Extended timeout for large PDF downloads
        llm_timeout=90,  # Standard timeout for analysis
        use_thinking=True,  # Enable thinking for analytical decisions
        vision_detail_level='high',  # High detail for financial data accuracy
        
        # Document tracking
        generate_gif=False,  # No GIF for professional use
        calculate_cost=True,  # Track costs for research budget
        
        # Enhanced file handling
        available_file_paths=[str(downloads_dir)],  # Track downloaded files
        
        # Financial analyst system prompt enhancement
        extend_system_message="""
FINANCIAL ANALYST PROTOCOL:
- Prioritize official sources (SEC, company IR pages, established financial institutions)
- Verify document authenticity before download
- Check PDF file sizes and formats for legitimacy
- Organize downloads with clear naming conventions
- Report any suspicious or inaccessible content
- Focus on recent documents (last 2 years preferred)
- Extract key financial metrics when possible
- Maintain professional research standards
- Respect rate limits and website terms of service
        """,
    )
    
    start_time = asyncio.get_event_loop().time()
    
    try:
        print("\n🚀 Starting financial research automation...")
        print("📋 Phase 1: SEC EDGAR filings research")
        print("📋 Phase 2: Company investor relations")
        print("📋 Phase 3: Financial research platforms")
        print("📋 Phase 4: Document organization")
        
        result = await agent.run(max_steps=25)  # Extended steps for comprehensive research
        end_time = asyncio.get_event_loop().time()
        
        execution_time = end_time - start_time
        print(f"\n✅ Financial research completed in {execution_time:.2f} seconds")
        
        # Check downloaded files
        downloaded_files = list(downloads_dir.glob('*.pdf'))
        print(f"\n📁 Downloaded Documents Summary:")
        print(f"   📊 Total PDFs downloaded: {len(downloaded_files)}")
        
        if downloaded_files:
            print(f"   📋 Document List:")
            for file in downloaded_files:
                file_size = file.stat().st_size / (1024 * 1024)  # Size in MB
                print(f"     • {file.name} ({file_size:.1f} MB)")
        else:
            print("   ⚠️  No PDF documents were downloaded")
        
        print(f"\n📊 Research Results: {result}")
        
        # Financial analyst metrics
        print(f"\n📈 Research Session Metrics:")
        print(f"   ⏱️  Total research time: {execution_time:.2f}s")
        print(f"   📁 Documents collected: {len(downloaded_files)}")
        print(f"   🎯 Target companies: Microsoft, Apple, Google")
        print(f"   💾 Storage location: {downloads_dir}")
        
        # Next steps recommendation
        print(f"\n🔄 Recommended Next Steps:")
        print(f"   1. Review downloaded documents for completeness")
        print(f"   2. Extract key financial metrics using PDF analysis tools")
        print(f"   3. Create comparative analysis spreadsheet")
        print(f"   4. Set up monitoring for new filings and reports")
        
    except Exception as e:
        end_time = asyncio.get_event_loop().time()
        print(f"\n❌ Research automation failed after {end_time - start_time:.2f} seconds")
        print(f"🚫 Error: {e}")
        print("\n🔧 Troubleshooting for Financial Research:")
        print("   • Verify internet connectivity to financial websites")
        print("   • Check SEC EDGAR system availability")
        print("   • Ensure downloads directory has write permissions")
        print("   • Verify company investor relations pages are accessible")
        print("   • Consider running during business hours for better site availability")
        
        # Check partial downloads
        partial_files = list(downloads_dir.glob('*.pdf'))
        if partial_files:
            print(f"\n📁 Partial Results: {len(partial_files)} documents downloaded before failure")
    
    finally:
        if agent.browser_session:
            print("\n🧹 Closing research session...")
            await agent.browser_session.close()

if __name__ == '__main__':
    print("🔧 Financial Analyst Configuration:")
    print("   • Research Focus: Technology sector (MSFT, AAPL, GOOGL)")
    print("   • Document Types: 10-K, 10-Q, earnings, ESG reports")
    print("   • Sources: SEC EDGAR, company IR, Yahoo Finance")
    print("   • Downloads: Organized in ~/Downloads/financial_research/")
    print("   • Compliance: Public documents only, terms of service respected")
    print("   • Analysis: Revenue, profitability, cash flow, ESG metrics")
    print()
    
    # Verify OpenAI API key
    if not os.getenv('OPENAI_API_KEY'):
        print("❌ OPENAI_API_KEY environment variable not set!")
        print("🔑 Required for financial analysis capabilities")
        sys.exit(1)
    
    asyncio.run(main())