# verifies the news articles from a list of urls , uses google search to find related articles and then uses llm to verify the news article and makes a report out of it 
import asyncio
import csv
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
from urllib.parse import urlparse, quote_plus

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from browser_use import ActionResult, Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize controller
controller = Controller()

class RelatedArticle(BaseModel):
    title: str
    url: str
    source: str
    content: Optional[str] = None

class NewsArticle(BaseModel):
    title: str
    content: str
    source: str
    url: str
    related_articles: List[RelatedArticle] = []
    verdict: str  # "Reliable", "Unreliable", "Inconclusive"
    reasoning: str
    confidence: Optional[float] = None

@controller.action('Save news verification results', param_model=NewsArticle)
def save_news_verification(article: NewsArticle):
    # Save to CSV
    with open('news_verification.csv', 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            article.title, 
            article.source,
            article.url, 
            article.verdict,
            article.confidence
        ])
    
    # Save report
    report_filename = f"reports/{article.title.replace(' ', '_')[:30].replace('/', '_')}.txt"
    os.makedirs(os.path.dirname(report_filename), exist_ok=True)
    
    with open(report_filename, 'w', encoding='utf-8') as f:
        f.write(f"NEWS VERIFICATION REPORT\n\n")
        f.write(f"Title: {article.title}\n")
        f.write(f"Source: {article.source}\n")
        f.write(f"URL: {article.url}\n\n")
        f.write(f"RELATED ARTICLES COMPARED:\n")
        for i, related in enumerate(article.related_articles, 1):
            f.write(f"{i}. {related.title}\n")
            f.write(f"   Source: {related.source}\n")
            f.write(f"   URL: {related.url}\n\n")
        f.write(f"VERDICT: {article.verdict.upper()}\n")
        f.write(f"Confidence: {article.confidence}/10\n\n")
        f.write(f"ANALYSIS:\n{article.reasoning}\n")
    
    return f'Saved verification for: {article.title}'

@controller.action('Extract article content')
async def extract_article_content(browser: BrowserContext):
    # Extract title
    title_element = await browser.get_dom_element_by_selector('h1')
    title = await title_element.get_text() if title_element else "Title not found"
    
    if title == "Title not found":
        # Try alternate selectors for title
        title_selectors = ['.article-title', '.headline', '.entry-title', '[itemprop="headline"]']
        for selector in title_selectors:
            title_element = await browser.get_dom_element_by_selector(selector)
            if title_element:
                title = await title_element.get_text()
                if title:
                    break
    
    # Extract content - try different common selectors
    content_selectors = ['article', '.article-body', '.article-content', 'main', '.story-body']
    content = ""
    
    for selector in content_selectors:
        content_element = await browser.get_dom_element_by_selector(selector)
        if content_element:
            content = await content_element.get_text()
            if content and len(content) > 100:  # Ensure meaningful content
                break
    
    if not content:
        # Fallback to paragraphs
        paragraphs = await browser.get_dom_elements_by_selector('p')
        content_parts = []
        for p in paragraphs:
            text = await p.get_text()
            if text and len(text) > 30:  # Filter navigation items
                content_parts.append(text)
        content = "\n".join(content_parts)
    
    # Get source from URL
    url = await browser.get_current_url()
    domain = urlparse(url).netloc
    source = domain.replace('www.', '')
    
    return ActionResult(extracted_content=f"TITLE: {title}\nSOURCE: {source}\nURL: {url}\nCONTENT: {content}")

@controller.action('Search headline on Google')
async def search_headline_on_google(headline: str, browser: BrowserContext):
    # Clean and encode the headline for search
    search_query = quote_plus(headline)
    search_url = f"https://www.google.com/search?q={search_query}"
    
    # Go to Google search
    await browser.goto(search_url)
    await asyncio.sleep(2)  # Wait for search results to load
    
    # Extract search results
    search_results = []
    
    # Get all result elements
    result_elements = await browser.get_dom_elements_by_selector('.g')
    
    for i, result in enumerate(result_elements):
        if i >= 5:  # Get top 5 results to filter from later
            break
            
        # Extract title
        title_element = await result.query_selector('h3')
        title = await title_element.get_text() if title_element else "Title not found"
        
        # Extract URL
        link_element = await result.query_selector('a')
        url = await link_element.get_attribute('href') if link_element else "URL not found"
        
        # Get source domain
        if url != "URL not found":
            domain = urlparse(url).netloc
            source = domain.replace('www.', '')
        else:
            source = "Unknown source"
        
        search_results.append({
            "title": title,
            "url": url,
            "source": source
        })
    
    return ActionResult(search_results=search_results)

@controller.action('Visit and analyze news article')
async def visit_news_article(url: str, browser: BrowserContext):
    # Navigate to the article
    await browser.goto(url)
    await asyncio.sleep(2)  # Wait for page to load
    
    # Extract article content
    extract_result = await extract_article_content(browser)
    if extract_result.error:
        return ActionResult(error=f"Failed to extract article: {extract_result.error}")
    
    # Parse the extracted content
    content_lines = extract_result.extracted_content.split('\n')
    article_data = {}
    
    for line in content_lines:
        if line.startswith('TITLE:'):
            article_data['title'] = line.replace('TITLE:', '').strip()
        elif line.startswith('SOURCE:'):
            article_data['source'] = line.replace('SOURCE:', '').strip()
        elif line.startswith('URL:'):
            article_data['url'] = line.replace('URL:', '').strip()
        elif line.startswith('CONTENT:'):
            article_data['content'] = line.replace('CONTENT:', '').strip()
    
    # Search headline on Google
    search_result = await search_headline_on_google(article_data['title'], browser)
    
    if search_result.error:
        return ActionResult(error=f"Failed to search headline: {search_result.error}")
    
    # Prepare related articles data
    related_articles = []
    
    # Filter search results to avoid the original URL
    filtered_results = [r for r in search_result.search_results if r['url'] != article_data['url']]
    
    # Only take the top 2 results
    verification_candidates = filtered_results[:2]
    
    # Process each candidate
    for result in verification_candidates:
        # Visit the related article
        await browser.goto(result['url'])
        await asyncio.sleep(2)  # Wait for page to load
        
        # Extract content
        related_content = await extract_article_content(browser)
        
        if not related_content.error:
            # Parse the content
            related_data = {}
            for line in related_content.extracted_content.split('\n'):
                if line.startswith('CONTENT:'):
                    related_data['content'] = line.replace('CONTENT:', '').strip()
            
            # Create RelatedArticle object
            related_article = RelatedArticle(
                title=result['title'],
                url=result['url'],
                source=result['source'],
                content=related_data.get('content', "")
            )
            related_articles.append(related_article)
    
    # Return to original article
    await browser.goto(article_data['url'])
    
    # Combine all data
    combined_data = {
        "original_article": article_data,
        "related_articles": [r.dict() for r in related_articles]
    }
    
    return ActionResult(article_analysis=combined_data)

# Initialize browser
browser = Browser(
    config=BrowserConfig(
        # Use your browser path if needed
        # chrome_instance_path='C:/Program Files/Google/Chrome/Application/chrome.exe',
        disable_security=True,
    )
)

async def main():
    # Create reports directory
    Path("reports").mkdir(exist_ok=True)
    
    # Create CSV file if it doesn't exist
    if not os.path.exists('news_verification.csv'):
        with open('news_verification.csv', 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Title', 'Source', 'URL', 'Verdict', 'Confidence'])
    
    # Read URLs from links.txt
    #Make a links.txt file in the same directory as the script and add the urls of the news articles you want to verify
    try:
        with open('links.txt', 'r') as f:
            news_links = [line.strip() for line in f.readlines() if line.strip()]
    except FileNotFoundError:
        print("No links.txt file found. Please create one with news article URLs.")
        return

    if not news_links:
        print("No links found in links.txt")
        return

    # Initialize LLM
    model = ChatOpenAI(
        model='gpt-4o',
        temperature=0.2
    )

    # Create agent with instructions
    agent = Agent(
        task="News Verification Task\n\n"
             "For each news article URL in the provided list:\n"
             "1. Visit the URL and extract the article content and headline\n"
             "2. Search for the headline on Google\n"
             "3. Compare the original article with exactly 2 related articles found on Google\n"
             "4. Analyze the article for credibility and factual accuracy\n"
             "5. Determine a verdict: Reliable, Unreliable, or Inconclusive\n"
             "6. Provide detailed reasoning for the verdict\n"
             "7. Save verification results\n\n"
             "Analysis criteria:\n"
             "- Source credibility\n"
             "- Consistency with how other outlets are reporting the same story\n"
             "- Evidence provided\n"
             "- Logical consistency\n"
             "- Bias and emotional manipulation\n"
             "- Consistency with known facts\n"
             "- Use of authoritative sources\n\n"
             f"Article URLs to verify:\n{chr(10).join(news_links)}",
        llm=model,
        controller=controller,
        browser=browser
    )

    await agent.run()

if __name__ == '__main__':
    asyncio.run(main())